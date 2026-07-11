# 293 — 메모리 provider 공통 조상: 축(user_id) 골격 통일, 반복 제거

## 배경

사용자 지적(2026-07-11, provider 6개 열람): "공통 조상을 만들면 반복 구현이 줄겠다." 실측 결과
**절반 맞다** — 6개 전부는 아니고 **메모리 3형제(Memory 읽기·Write·Edit)**로 좁히면 정확하다.

- **Agent/Mcp/Rag**: 계약(_CapabilityProvider Protocol)만 공유·내부는 근본 상이(backing이
  Agent/_McpBacking/_RagBacking, candidates/load가 DB쿼리 vs MCP연결 vs 컬렉션조회, 공유 헬퍼
  `_cap` 0개). 공통 조상=본체 없는 껍데기 → **억지 상속(OUT)**. 시그니처 반복은 Protocol이 이미 강제.
- **Memory 3형제**: `_MemBacking`을 이미 공유하고 6메서드 중 4개가 파라미터만 다른 반복(실측):

| 메서드 | 3형제 | 조상 이관 |
|---|---|---|
| `__init__(session_factory, user_id)` | 완전 동일 | ✅ 조상 |
| `describe` | 완전 동일 (`self._cap(with_schema=True)`) | ✅ 조상 `@final` |
| `_cap(with_schema)` | 구조 동일, id/name/hook/schema 값만 다름 | ✅ 조상(자식 클래스 속성 읽음) |
| `candidates(allow)` | 구조 동일, KIND+파서만 다름 | ✅ 조상 `@final` |
| `load(cap_id)` | 구조 동일, 파서만 다름 | ✅ 조상 `@final` |
| `node_label` | 구조 동일, KIND만 다름 | ✅ 조상 |
| **`invoke`** | 진짜 다름(읽기/쓰기/수정삭제) | ⛔ 자식 `@abstractmethod` |
| **`approval_for`** | 진짜 다름(None/항상/소유권+승인) | ⛔ 자식 `@abstractmethod` |

파서 통일: candidates/load의 `_parse_mem/_parse_memwrite/_parse_memedit(a) == "user"`는 전부
common.py의 기존 `_cap_resource(cap_id, kind)`(kind별 파서 디스패치, core._permitted도 사용)로
**단일화** 가능 → 조상이 `_cap_resource(a, self.kind) == self.RESOURCE`로 판정, 파서 지식 불요.

선례: **이 코드베이스에 이미 있는 패턴**(OrchestrationAgentBase — ABC + 템플릿 메서드 + `@final`).
같은 패턴을 적용 = 중복 제거 + 관례 일관.

## 목표 (측정 가능)

1. **`MemoryAxisProvider(ABC)` 신설** — 축(user_id) provider의 골격 소유:
   - 소유(구현): `__init__`, `_cap`, `describe`(`@final`), `candidates`(`@final`), `load`(`@final`),
     `node_label`. `_cap`은 자식 클래스 속성(`CAP_ID`·`CAP_NAME`·`CAP_HOOK`·`INPUT_SCHEMA`)을 읽어 조립.
   - 추상: `invoke`, `approval_for`(`@abstractmethod`). 자식이 채우는 **유일한 구멍**.
   - 클래스 속성 계약: `kind`(=CAP_KIND_*), `RESOURCE = "user"`, 위 4개 표시 속성.
2. **3자식 이름 불변**(재수출 계약) — `MemoryProvider`(읽기)·`MemoryWriteProvider`·`MemEditProvider`가
   조상 상속으로 축소. 각자 남는 것 = 클래스 속성 + invoke + approval_for(+ Edit의 _validate/_apply).
   `broker/core.py`·`broker/__init__.py`·verify_104/105/111 import 경로 **무변경**.
3. **행위 보존** — 관측 가능 동작(반환 Capability·InvokeResult·승인 payload·node_label 문자열)이
   바이트 동일. anti-leak 불변식(user_id는 principal 도출만·args 무시)·승인 게이트·소유권 선행 유지.
4. 조상은 ABC(추상 미구현)라 인스턴스화·레지스트리 등록 안 됨. `_CapabilityProvider` Protocol 구조
   적합은 자식이 만족(조상+자식 합쳐 6메서드 완비).

## 설계

- `MemoryAxisProvider`를 memory.py 상단(파서·_MemBacking 뒤)에 둔다. 3자식이 상속.
- `_cap`: 조상이 `Capability(id=self.CAP_ID, kind=self.kind, name=self.CAP_NAME, hook=self.CAP_HOOK)`
  조립, `with_schema`면 `self.INPUT_SCHEMA` 부착. 자식은 값만 선언(코드 0).
- `candidates`/`load`: 조상이 `self._user_id` 게이트 + `_cap_resource(_, self.kind)==self.RESOURCE`
  판정 + `_MemBacking(self.RESOURCE)` 반환. 3자식에서 이 로직 삭제.
- `@final`(describe·candidates·load): 자식 재정의 = 불변식 우회 → 타입체커가 잡음(orchestrate 선례).
- invoke/approval_for는 자식 그대로 이동(본문 무변경). Edit의 `_validate`/`_apply`/`_memedit_args`,
  Write의 `_memwrite_text`, 모듈 상수(MEMWRITE_*·MEMEDIT_*)는 위치·본문 무변경.
- `node_label`: 조상이 `f"broker_invoke:{self.kind}:{self.RESOURCE}"`.

## 검증

- **행위 보존 실측**: verify_104(read)·105(write)·111(edit) 통과 + 실모델 스위트 51/51.
- **구조 단언**: 3자식이 `MemoryAxisProvider` 서브클래스·`_CapabilityProvider` 적합(isinstance/구조).
  조상은 ABC라 직접 인스턴스화 시 TypeError.
- **재수출 무변경**: `sorted(vars(api.broker))` 여집합 0(자식 이름·심볼 소실 0).
- **수치**: memory.py 줄 수 감소(중복 제거) 측정, `make metrics` 전판, ruff/mypy 0.
- **codex 적대**: anti-leak(user_id 도출·args 무시)·승인 게이트·소유권 선행이 조상 이관 후에도
  물리적으로 유지되는가(3자식 공유 candidates/load가 kind 오분류로 교차 축 여는 틈 없나).

## OUT
- Agent/Mcp/Rag 공통 조상(억지 상속 — 이득 없음). provider Protocol 자체 변경(계약 불변).
- mem0 scope-bound 원자 mutation(check-then-act 잔존은 스펙 111이 이미 정직 기록 — 범위 밖).
