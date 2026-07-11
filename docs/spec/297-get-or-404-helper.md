# 297 — get-or-404 정본화: 순수 PK-존재 체크 단일화 (소유권 경계 불변)

## 배경

스펙 296에서 분리한 마지막 B. `obj = await session.get(Model, id)` + `if obj is None: raise
HTTPException(404, ...)` 관용구가 **37곳**에 반복(blocks 13·providers 5·model_registry 4·rag 2·
user_admin 3·eval_* 8·agents 1·chat_context 1). 이미 `_get_session_or_404`·`_dataset_or_404` 선례 존재.

> **전수조사 정정(스펙 승인 후)**: 초기 분류 스크립트는 *단일 줄·꼬리주석 없는* 형태만 매칭해 33건을
> 잡았다. 하지만 멀티라인 `session.get(\n …)`·`if (\n X is None\n):`·꼬리 인라인 주석으로 형태만
> 어긋난 **동일 순수 패턴 4건**(eval_cases 2·eval_authoring 2)이 남아 있었다 — 전부 `assert_may_manage`
> *이전*의 존재-404(결합 아님). 정규식이 놓친 걸 "무해 near-miss"로 방치하면 딱 "좁은 렌즈의 0"이라,
> 견고 스캐너(멀티라인·괄호 허용, 조건에 or/and 없을 때만 순수 판정)로 재전수해 **37건 전부 편입**.

## RBAC 경계 (체크리스트 트리거 — 소유권·존재 비노출)

**핵심 안전 규칙**: `session.get(M, id)`는 **항상 PK 순수 조회**다(소유권 스코프 fetch는 `select().
where()`·`scalar_one_or_none`을 쓰지 `.get`을 안 쓴다). 따라서 위험은 오직 **결합 게이트**
(`if X is None or not may_...`)뿐 — 이건 변환 대상에서 **제외**한다. 변환은 **정확히 `if X is None:`
단독 + 다음 줄 404 raise** 형태만(결합·`is not None`·`return`·비-404는 자동 제외).

- **제외 실측(29건)**: 결합 게이트(a2a_server:42·chat:213·memory_routes:37·eval_runs:298 등),
  `if X is None: return`(early-return — 404 아님, 변환 시 버그), inline 코멘트로 형태 어긋난 것.
  분류 스크립트가 셋을 물리적으로 가른다(자가판정 아닌 측정).
- get_or_404는 **존재 체크만** — 소유권/가시성 게이트를 대체하지 않는다. 변환 후에도 각 라우터의
  별도 `assert_may_manage`·SELECT-WHERE·404-fold는 그대로.

## 목표 (측정 가능)

1. **`db.get_or_404(session, model, id, detail="not found")` 신설** — 3줄을 1줄로. 존재 없으면 404.
2. **37곳 변환**: 순수 존재-404 패턴만(멀티라인·꼬리주석 형태 포함). detail 문자열 **정확 보존**
   ("not found" 기본은 생략, 그 외 명시). 측정: 견고 스캐너로 순수 패턴 잔존 37→0, get_or_404 호출 37.
3. **제외(결합 게이트·early-return·비표준) 무변경**: 손대지 않음(측정으로 확인).
4. **행위 보존**: 존재 404·detail 문자열·404-fold(존재 비노출)·소유권 게이트 전부 불변.
   verify(112 소유권·147 가시성·148·104·103 + 관련) + 스위트 51/51 + codex 적대(가시성 게이트 탈락 없나).

## 설계

```python
_T = TypeVar("_T")
async def get_or_404(session: AsyncSession, model: type[_T], ident: object,
                     detail: str = "not found") -> _T:
    """PK 조회 후 없으면 404(정본, 스펙 297). **순수 존재 체크만** — 소유권/가시성은 호출부가 별도로.
    session.get은 항상 PK 조회라 스코프 우회 위험 없음(SELECT-WHERE 대체 아님)."""
    obj = await session.get(model, ident)
    if obj is None:
        raise HTTPException(status_code=404, detail=detail)
    return obj
```
- db.py에 둔다(이미 `get_session` FastAPI 의존자를 호스팅 = route-layer 헬퍼 홈).
- 변환: `obj = await get_or_404(session, Model, id[, detail=D])`. 반환 obj는 뒤 로직·소유권 체크가 그대로 사용.
- import: 대부분 `from .db import get_or_404`(agents/ 하위만 `..db`). 기존 db import에 병합·ruff 정렬.

## 검증
- 분류 스크립트로 변환 33·제외 29 확정(전후 카운트). 순수 패턴 잔존 0.
- verify_112(소유권·per-cap)·147 가시성·148·104·103 + 스위트 51/51 + `make metrics-fast`(ruff/mypy 0).
- codex 적대: 변환이 (a) 결합 게이트를 잘못 삼켰나, (b) early-return을 404로 바꿨나, (c) detail 문자열
  드리프트, (d) 소유권/가시성 별도 게이트 탈락을 만들었나 — 여집합 공격.

## OUT
- 결합 게이트·early-return·`is not None`·비-404 None 체크(29곳) — 변환 금지.
- 소유권 스코프 fetch(`_get_session_or_404`·`_dataset_or_404`·SELECT-WHERE) — 이미 헬퍼거나 스코프 로직, 무변경.
- authz `_own_scope`/`_is_admin`·eval_* 내부 중복은 별도.
