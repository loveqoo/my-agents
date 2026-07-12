"""노드 라이브러리(스펙 316) — 등록 노드 CRUD + 버전 고정 참조의 단일 의미 소유 모듈.

노드형(스펙 259 계보) 노드를 (name, version) 단위 1급 자산으로 등록·공유한다. **발행 후 불변**
(수정 라우트를 만들지 않아 구조로 강제 — 수정=새 버전 발행). 에이전트 `nodes[]`는
`{"ref": {"name", "version"}}`으로 버전을 핀 고정 참조한다 — 새 버전 발행이 기존 참조 에이전트를
흔들지 않는다(테스트·출시 보호). floating latest 없음.

참조의 의미(해석·사용처 스캔·삭제 가드)는 전부 이 모듈이 소유한다(드리프트 0):
- `resolve_node_refs` — ref 항목을 등록 config **사본**으로 치환(순서 보존·원본 비오염·멱등).
  미해결 참조는 422로 명확히 실패(조용한 드롭·폴백 마스킹 금지 — 스펙 089 패턴).
- `node_ref_usage` — agents.config + agent_versions.config(버전 스냅샷·미리보기 실행도 참조 입구다)
  양쪽을 스캔해 (name, version)→에이전트 이름 집합을 얻는다.
- 삭제는 참조 존재 시 409 + 에이전트 이름 표면화(스펙 093 선례).
"""

import copy
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_principal
from .db import get_session
from .models import Agent, AgentVersion, NodeTemplate, User
from .naming import assert_valid_name
from .ownership import is_privileged, may_use_agent
from .schemas import AgentConfig

router = APIRouter(prefix="/node-templates", tags=["node-templates"])


async def require_node_manage(principal: User | str = Depends(current_principal)) -> User | str:
    """노드 라이브러리 변이 게이트(codex 316 P1) — 등록 노드는 여러 에이전트가 실행하는 **공유
    실행 자산**이라 발행/삭제는 특권(머신 토큰·superuser·admin)만. member는 403. 읽기(목록·상세)는
    인증만 — 에이전트 폼의 참조 픽커가 소비한다. model_registry.require_model_manage와 동일 패턴."""
    if not is_privileged(principal):
        raise HTTPException(status_code=403, detail="등록 노드 관리 권한이 없습니다")
    return principal


_manage = Depends(require_node_manage)


async def _lock_template_name(db: AsyncSession, name: str) -> None:
    """이름 단위 pg advisory **xact** lock(codex 316 P1 — 삭제 가드 TOCTOU). 발행(max+1 계산→insert)·
    삭제(usage 스캔→delete)·에이전트 저장(ref 존재 검증→commit)이 같은 키로 직렬화돼, "삭제가
    usage=0을 본 뒤 새 참조가 저장되고 삭제가 커밋"되는 레이스(dangling ref)를 닫는다. JSONB 참조라
    FK가 없어 잠금이 유일한 직렬화 수단. 트랜잭션 종료(commit/rollback) 시 자동 해제."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"nodetpl:{name}"}
    )


# ----------------------------- 참조 의미(공용 헬퍼) -----------------------------
def iter_node_refs(nodes: object) -> list[tuple[str, int]]:
    """nodes[]에서 (name, version) 참조 키를 순서대로 추출(비참조·잡값은 건너뜀). 순수 함수."""
    out: list[tuple[str, int]] = []
    if not isinstance(nodes, list):
        return out
    for n in nodes:
        ref = n.get("ref") if isinstance(n, dict) else None
        if (
            isinstance(ref, dict)
            and isinstance(ref.get("name"), str)
            and isinstance(ref.get("version"), int)
            and not isinstance(ref.get("version"), bool)
        ):
            out.append((ref["name"], ref["version"]))
    return out


async def resolve_node_refs(db: AsyncSession, nodes: list) -> list:
    """ref 항목을 등록 노드 config **사본**으로 치환(스펙 316). 인라인 항목은 그대로 통과라
    이미 해석된 리스트에 재적용해도 무변화(멱등). 사본(deepcopy)이라 하류(오버라이드 병합·모델
    해석)가 변형해도 등록 원본은 비오염. 표시 이름이 비면 등록 이름을 기본값으로(트레이스 가독).
    미해결 참조(삭제·미존재)는 **422로 명확히 실패** — 반쪽 파이프라인을 조용히 돌리지 않는다."""
    keys = set(iter_node_refs(nodes))
    if not keys:
        return nodes
    rows = (
        (
            await db.execute(
                select(NodeTemplate).where(NodeTemplate.name.in_({k[0] for k in keys}))
            )
        )
        .scalars()
        .all()
    )
    by_key = {(t.name, t.version): t for t in rows}
    out: list = []
    for n in nodes:
        ref = n.get("ref") if isinstance(n, dict) else None
        if not isinstance(ref, dict):
            out.append(n)
            continue
        tpl = by_key.get((ref.get("name"), ref.get("version")))
        if tpl is None:
            raise HTTPException(
                status_code=422,
                detail=f"노드 참조 미해결: {ref.get('name')}@{ref.get('version')} — "
                "등록 노드에 없는 이름/버전입니다(삭제되었거나 오타).",
            )
        cfg = copy.deepcopy(tpl.config or {})
        cfg.setdefault("name", tpl.name)
        out.append(cfg)
    return out


async def node_ref_usage(db: AsyncSession) -> dict[tuple[str, int], list[Agent]]:
    """(name, version) → 참조 에이전트(ORM 객체, pk 중복 제거). 입구 열거(닫힌 집합): ① agents.config
    (서빙 설정) ② agent_versions.config(버전 스냅샷 — 핀 버전 미리보기 실행이 이 config를 로드하므로
    참조 입구다). 오버라이드는 ref를 받지 않아(_NODE_OVERRIDE_FIELDS 밖) 입구가 아니다. impl과
    무관하게 nodes의 ref를 전부 센다(보수적 가드 — impl을 나중에 pipeline으로 바꿔도 참조가 살아
    있어야 한다). 에이전트 수가 작아 앱 사이드 스캔으로 충분(usage 표시와 삭제 가드가 같은 함수 =
    드리프트 0). 객체를 돌려주는 이유(codex 316 P1): 조회 응답의 이름 노출은 가시성(may_use_agent)
    필터를 거쳐야 하는데, 이름 문자열만 돌려주면 필터할 근거가 없다."""
    usage: dict[tuple[str, int], dict[object, Agent]] = {}
    agents = (await db.execute(select(Agent))).scalars().all()
    by_pk = {a.id: a for a in agents}
    for a in agents:
        for key in iter_node_refs((a.config or {}).get("nodes")):
            usage.setdefault(key, {})[a.id] = a
    versions = (await db.execute(select(AgentVersion.agent_pk, AgentVersion.config))).all()
    for agent_pk, cfg in versions:
        a = by_pk.get(agent_pk)
        if a is None:
            continue
        for key in iter_node_refs((cfg or {}).get("nodes")):
            usage.setdefault(key, {})[a.id] = a
    return {k: list(v.values()) for k, v in usage.items()}


def visible_used_by(agents: list[Agent], principal: User | str | None) -> tuple[list[str], int]:
    """usedBy 이름 노출 필터(codex 316 P1 — private 에이전트 이름 열거 차단): 요청 주체가 볼 수 있는
    (may_use_agent) 에이전트 이름만 + 나머지는 개수로. 삭제 가드(특권 전용)는 필터 없이 전체를 본다.
    순수 함수(단위 검증)."""
    visible = [a for a in agents if may_use_agent(a, principal)]
    return sorted({a.name for a in visible}), len(agents) - len(visible)


async def assert_node_refs_exist(db: AsyncSession, nodes: object) -> None:
    """에이전트 저장 시 ref 존재 검증(codex 316 P1 — impl 비대칭 봉합): impl이 무엇이든 nodes에 ref가
    있으면 전부 존재해야 저장된다(실행 시 422로 터질 시한폭탄을 저장 시점에 이른 실패). 참조 이름에
    advisory lock을 걸어 삭제 가드와 직렬화 — 검증 통과 후 이 트랜잭션이 커밋되기 전에 템플릿이
    삭제되는 레이스(dangling ref)를 닫는다. 이름은 정렬 순으로 잠근다(교착 회피)."""
    keys = set(iter_node_refs(nodes))
    if not keys:
        return
    for name in sorted({k[0] for k in keys}):
        await _lock_template_name(db, name)
    rows = (
        await db.execute(
            select(NodeTemplate.name, NodeTemplate.version).where(
                NodeTemplate.name.in_({k[0] for k in keys})
            )
        )
    ).all()
    existing = {(n, v) for n, v in rows}
    missing = sorted(keys - existing)
    if missing:
        raise HTTPException(
            status_code=422,
            detail="노드 참조 미해결: "
            + ", ".join(f"{n}@{v}" for n, v in missing)
            + " — 등록 노드에 없는 이름/버전입니다(삭제되었거나 오타).",
        )


# ----------------------------- 스키마 -----------------------------
class NodeTemplateIn(BaseModel):
    name: str = Field(max_length=120)  # 식별 이름(규칙, 스펙 148 준용) — DB String(120) 정합
    description: str | None = Field(default=None, max_length=200)
    config: dict[str, Any]  # 노드 설정 — 에이전트 nodes 항목과 동일 화이트리스트(_normalize_node)


class NodeTemplateVersionOut(BaseModel):
    id: str
    version: int
    kind: str
    description: str | None
    config: dict[str, Any]
    created_at: str | None
    usedBy: list[str]  # 이 버전을 핀 참조하는 에이전트 이름(요청 주체 가시 범위만 — codex 316 P1)
    usedByHidden: int = 0  # 가시 범위 밖(비공개) 참조 에이전트 수 — 이름 없이 개수만(정직 표기)


class NodeTemplateGroupOut(BaseModel):
    name: str
    kind: str
    description: str | None  # 최신 버전의 설명
    latestVersion: int
    versionCount: int
    usedByCount: int  # 전 버전 합산 distinct 에이전트 수


class NodeTemplateDetailOut(BaseModel):
    name: str
    versions: list[NodeTemplateVersionOut]  # 최신 먼저


def _validated_template_config(config: object) -> dict[str, Any]:
    """등록 노드 config 검증 — 에이전트 저장 스키마의 노드 화이트리스트(_normalize_node)를 **재사용**
    (드리프트 0). 등록 노드 자신이 참조(ref)일 수는 없다(중첩 참조=순환 클래스 원천 배제)."""
    if not isinstance(config, dict):
        raise HTTPException(status_code=422, detail="config는 객체여야 합니다.")
    if "ref" in config:
        raise HTTPException(
            status_code=422, detail="등록 노드 config는 참조(ref)일 수 없습니다(중첩 참조 없음)."
        )
    try:
        return AgentConfig._normalize_node(config)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


# ----------------------------- 라우트 -----------------------------
@router.get("", response_model=list[NodeTemplateGroupOut])
async def list_node_templates(
    session: AsyncSession = Depends(get_session),
) -> list[NodeTemplateGroupOut]:
    rows = (
        (
            await session.execute(
                select(NodeTemplate).order_by(NodeTemplate.name, NodeTemplate.version.desc())
            )
        )
        .scalars()
        .all()
    )
    usage = await node_ref_usage(session)
    groups: dict[str, NodeTemplateGroupOut] = {}
    for t in rows:  # 이름별 첫 행 = 최신 버전(정렬 보장)
        g = groups.get(t.name)
        if g is None:
            # 개수만 노출(이름 없음) — 가시성 누출 없이 전 버전 합산 distinct 에이전트 수.
            used = {a.id for (n, _v), agents in usage.items() if n == t.name for a in agents}
            groups[t.name] = NodeTemplateGroupOut(
                name=t.name,
                kind=t.kind,
                description=t.description,
                latestVersion=t.version,
                versionCount=1,
                usedByCount=len(used),
            )
        else:
            g.versionCount += 1
    return list(groups.values())


@router.get("/{name}", response_model=NodeTemplateDetailOut)
async def get_node_template(
    name: str,
    session: AsyncSession = Depends(get_session),
    principal: User | str = Depends(current_principal),
) -> NodeTemplateDetailOut:
    rows = (
        (
            await session.execute(
                select(NodeTemplate)
                .where(NodeTemplate.name == name)
                .order_by(NodeTemplate.version.desc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="node template not found")
    usage = await node_ref_usage(session)
    versions: list[NodeTemplateVersionOut] = []
    for t in rows:
        # usedBy 이름은 요청 주체가 볼 수 있는 에이전트만(codex 316 P1) — 나머지는 개수로 정직 표기.
        names, hidden = visible_used_by(usage.get((t.name, t.version), []), principal)
        versions.append(
            NodeTemplateVersionOut(
                id=str(t.id),
                version=t.version,
                kind=t.kind,
                description=t.description,
                config=t.config or {},
                created_at=t.created_at.isoformat() if t.created_at else None,
                usedBy=names,
                usedByHidden=hidden,
            )
        )
    return NodeTemplateDetailOut(name=name, versions=versions)


@router.post("", response_model=NodeTemplateVersionOut, status_code=201, dependencies=[_manage])
async def create_node_template(
    body: NodeTemplateIn, session: AsyncSession = Depends(get_session)
) -> NodeTemplateVersionOut:
    """새 노드 등록(version=1) 또는 기존 이름에 **새 버전 발행**(다음 버전 자동). 발행 후 불변 —
    같은 (name, version) 재발행 없음(config 노드; 동일 버전 덮어쓰기는 스펙 317 코드 노드만).
    이름 잠금으로 동시 발행을 직렬화(codex 316 P2 — 경합 시 409 대신 둘 다 순서대로 발행)."""
    assert_valid_name(body.name)  # 식별 이름 규칙(스펙 148) — 서버가 진실원
    config = _validated_template_config(body.config)
    await _lock_template_name(session, body.name)
    latest = (
        await session.execute(
            select(NodeTemplate.version)
            .where(NodeTemplate.name == body.name)
            .order_by(NodeTemplate.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    tpl = NodeTemplate(
        name=body.name,
        version=(latest or 0) + 1,
        kind="config",
        config=config,
        description=(body.description or "").strip() or None,
    )
    session.add(tpl)
    try:
        await session.commit()
    except IntegrityError as e:
        # 동시 발행 경합 — unique(name, version)이 최종 심판(레이스에도 중복 버전 불가).
        raise HTTPException(
            status_code=409, detail="같은 버전이 동시에 발행되었습니다 — 다시 시도하세요."
        ) from e
    await session.refresh(tpl)
    return NodeTemplateVersionOut(
        id=str(tpl.id),
        version=tpl.version,
        kind=tpl.kind,
        description=tpl.description,
        config=tpl.config or {},
        created_at=tpl.created_at.isoformat() if tpl.created_at else None,
        usedBy=[],
    )


@router.delete("/{name}/{version}", status_code=204, dependencies=[_manage])
async def delete_node_template(
    name: str, version: int, session: AsyncSession = Depends(get_session)
) -> None:
    """참조 에이전트가 있으면 409 + 이름 표면화(스펙 093 선례) — 핀 참조를 끊는 삭제는 실행 시
    422(미해결)로 터질 시한폭탄이라 애초에 막는다. 참조 0이면 삭제. 이름 잠금이 스캔→삭제를
    에이전트 저장(assert_node_refs_exist)과 직렬화(codex 316 P1 TOCTOU). 삭제는 특권 전용 게이트
    뒤라 usedBy 이름을 필터 없이 표면화해도 가시성 누출이 아니다."""
    await _lock_template_name(session, name)
    tpl = (
        await session.execute(
            select(NodeTemplate).where(NodeTemplate.name == name, NodeTemplate.version == version)
        )
    ).scalar_one_or_none()
    if tpl is None:
        raise HTTPException(status_code=404, detail="node template not found")
    usage = await node_ref_usage(session)
    used_by = sorted({a.name for a in usage.get((name, version), [])})
    if used_by:
        raise HTTPException(
            status_code=409,
            detail=f"{name}@{version}을(를) 참조하는 에이전트가 있어 삭제할 수 없습니다: "
            + ", ".join(used_by),
        )
    await session.delete(tpl)
    await session.commit()
