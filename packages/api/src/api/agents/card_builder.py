"""A2A 카드 → Agent 빌더 (connect/external 공유).

코드 에이전트 토큰은 암호화 저장(출력은 serializer가 마스킹). 원격 인증 시 복호화 사용.
"""

from .. import crypto, net_guard
from ..models import Agent, AgentVersion
from .helpers import _new_agent_id, _today


def _clip(value: object, maxlen: int) -> str | None:
    """카드/매니페스트 문자열을 DB 컬럼 상한에 맞춰 안전화(적대리뷰 057 Finding 3).

    제3자가 거대/잡 문자열을 흘려도 Postgres bounded 컬럼(String(N))에서 commit이 500나지 않게,
    문자열이 아니면 None, 너무 길면 잘라 반환한다(표시·provenance 메타라 절단 허용)."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value[:maxlen]


def _norm_endpoint(raw: object) -> str | None:
    """카드 서비스 url을 절대 http(s)로 정규화해 저장(스펙 063, 빌더 하드닝).

    `fetch_card`가 이미 정규화하므로 정상 경로는 idempotent. fetch_card를 우회하는 미래 경로가
    스킴 없는 url을 흘려도 저장 데이터가 청결하게 유지된다(표시·probe도 같은 endpoint를 읽는다).
    정규화 불가(빈 값·비-http 스킴)면 clip한 raw를 그대로 보존 — 등록을 500내지 않고, 호출 경계
    (a2a_client, 스펙 063 D1)가 2차로 다시 시도한다."""
    clipped = _clip(raw, 400)
    if not clipped:
        return None
    try:
        return net_guard.normalize_http_url(clipped)
    except ValueError:
        return clipped


def _build_external_agent(
    card: dict, token: str | None, live: bool, card_url: str | None = None
) -> Agent:
    """제3자 A2A 카드 → external Agent. 불투명 카드 스냅샷, 로컬 모델/메모리/MCP 미해석(비로컬).

    카드 스냅샷은 config["card"], 서비스 URL은 endpoint, 호출 크레덴셜은 crypto.encrypt로 token에
    저장(2차 런타임 호출에서 복호 사용).

    card_url = 카드를 가져온 출처(.well-known 위치). resync 자가치유(스펙 081)가 이 URL로 카드를
    재fetch해 endpoint·status를 갱신한다 — 저장 안 하면 stale endpoint를 재연결 없이 못 고친다."""
    cfg = {
        "model": "",  # 외부는 로컬 모델 미해석
        "persona": "",
        "memories": [],
        "vectorTables": [],
        "mcps": [],
        "historyDepth": 10,
        "card": card,  # 등록 시점 카드 스냅샷(표시·검증 단일 소스)
        "cardUrl": card_url,  # 카드 출처 — resync 재해석용(스펙 081)
    }
    return Agent(
        agent_id=_new_agent_id(),
        name=_clip(card.get("name"), 200) or "외부 에이전트",
        source="external",
        model="",
        persona="",
        history_depth=10,
        config=cfg,
        exposed={"a2a": False},  # 우리가 소비측(클라이언트) — 서버측 노출과 무관
        status="online" if live else "offline",
        endpoint=_norm_endpoint(card.get("url")),
        token=crypto.encrypt(token) if token else None,
        registered_at=_today(),
        last_sync="방금",
    )


def _cfg_from_manifest(card: dict, ext: dict, card_url: str | None) -> dict:
    """ext["manifest"] → 저장 config dict(카드 스냅샷·cardUrl 포함, 잡 타입은 기본값으로 안전화)."""
    manifest = ext["manifest"]
    history_depth = manifest.get("historyDepth")
    if not isinstance(history_depth, int):
        history_depth = 10
    return {
        "model": manifest.get("model") or "",
        "persona": manifest.get("persona") or "",
        "memories": manifest.get("memories") if isinstance(manifest.get("memories"), list) else [],
        "vectorTables": [],
        "mcps": manifest.get("mcps") if isinstance(manifest.get("mcps"), list) else [],
        "historyDepth": history_depth,
        "card": card,  # 카드 스냅샷 — external과 동일하게 표시·검증 단일 소스
        "cardUrl": card_url,  # 카드 출처 — resync 재해석용(스펙 081)
    }


def _rows_from_card_versions(
    raw_versions: object, cfg: dict
) -> tuple[list[AgentVersion], str | None]:
    """카드 신고 versions → (AgentVersion 행 목록, 첫 active 버전 id). 잡값(비-dict·버전 없음)은 건너뜀."""
    versions: list[AgentVersion] = []
    active_version_id: str | None = None
    if isinstance(raw_versions, list):
        for raw_version in raw_versions:
            if not isinstance(raw_version, dict):
                continue
            vid = _clip(raw_version.get("version"), 40)
            if vid is None:
                continue
            vstatus = _clip(raw_version.get("status"), 20) or "archived"
            if vstatus == "active" and active_version_id is None:
                active_version_id = vid
            versions.append(
                AgentVersion(
                    version=vid,
                    status=vstatus,
                    note=raw_version.get("note")
                    if isinstance(raw_version.get("note"), str)
                    else "",
                    config=cfg,
                )
            )
    return versions, active_version_id


def _versions_from_deploy(deploy: dict, cfg: dict) -> tuple[list[AgentVersion], str | None]:
    """deploy.versions → (AgentVersion 목록, active 버전 id).

    active_version 불변식(적대리뷰 057 Finding 4): active_version은 항상 실재하는 active
    AgentVersion을 가리키거나 None. deploy.versions 잡값(빈 리스트·archived만·잡 버전)이 와도 active
    row 없이 active_version만 세팅되는 불일치를 만들지 않는다."""
    versions, active_version_id = _rows_from_card_versions(deploy.get("versions"), cfg)
    commit = _clip(deploy.get("commit"), 80)
    if active_version_id is None and commit:
        # 카드에 active 버전이 없으면 commit으로 active 1개 합성(external register와 일관). 합성한 뒤에만
        # active_version을 세팅 — 실재하는 row를 보장한다.
        synth = _clip(commit, 40)
        versions.append(
            AgentVersion(version=synth, status="active", note="Deploy · 카드 동기화", config=cfg)
        )
        active_version_id = synth
    return versions, active_version_id


def _build_code_agent_from_card(
    card: dict, ext: dict, token: str | None, live: bool, card_url: str | None = None
) -> Agent:
    """제1자(SDK 배포) A2A 카드 + my-agents 확장 → code Agent (스펙 057).

    config는 ext["manifest"](model/persona/mcps/…)에서 채우고 카드 스냅샷을 함께 보존한다.
    repo/commit/runtime·AgentVersion은 ext["deploy"]에서 만든다. **전부 카드에서 fetch — 프론트
    날조 없음**. A2A 호출엔 카드 url+token만 쓰지만(현 external과 동일), 저장 config는 1급 표시·resync용.
    """
    deploy = ext["deploy"]
    cfg = _cfg_from_manifest(card, ext, card_url)
    # 길이 하드닝(적대리뷰 057 Finding 3) — bounded 컬럼에 잡/거대 문자열이 들어가 commit이 500나지 않게.
    commit = _clip(deploy.get("commit"), 80)
    agent = Agent(
        agent_id=_new_agent_id(),
        name=_clip(card.get("name"), 200) or _clip(deploy.get("repo"), 200) or "SDK 에이전트",
        source="code",
        model=_clip(cfg["model"], 120) or "",
        persona=cfg["persona"],  # Text 컬럼 — 무제한
        history_depth=cfg["historyDepth"],
        config=cfg,
        exposed={"a2a": False},
        status="online" if live else "offline",
        endpoint=_norm_endpoint(card.get("url")),
        token=crypto.encrypt(token) if token else None,
        runtime=_clip(deploy.get("runtime"), 200),
        repo=_clip(deploy.get("repo"), 200),
        commit=commit,
        registered_at=_today(),
        last_sync="방금",
    )
    versions, active_version_id = _versions_from_deploy(deploy, cfg)
    agent.versions.extend(versions)
    agent.active_version = active_version_id
    return agent
