# 275 — llm_cfg 빌더 정본화 (스펙 300)

## 무엇을 했나
census 후보 C. `{base_url, api_key: crypto.decrypt(...), model_id}` llm_cfg 조립을 mem_config의 원자 2개로
단일화: `model_usable(cm) -> TypeGuard[ModelConfig]`(유효성 술어)·`llm_cfg_of(cm) -> dict`(연결 dict).
**8곳** 편입(eval 3·chat_context 3·mem_config 2 call). 무효 분기는 호출자별 존치.

## 배운 것 / 복리 포인트

- **census-lens 3연속 적중**(272·273에 이어). census 서브에이전트는 C를 eval 3곳으로 스코프했으나, 전역
  전수(`"api_key": crypto.decrypt` grep)하니 **동일 3-키 원자가 8곳**(chat_context 핫패스·mem_config 중첩
  포함). "0/3은 렌즈의 함수" — 서브에이전트 census도 렌즈가 좁을 수 있으니 메인이 전역 grep으로 재확인.
  사용자가 스코프를 AskUser로 "전체 원자" 선택(whole-fix). → [[whole-fix-over-minimal-patch]]

- **dedup이 mypy narrowing과 싸운다 — TypeGuard로 화해**. 인라인 술어(`cm is None or cm.provider is None
  or ...`)는 mypy에 narrowing을 주는데, 그걸 opaque 함수 `model_usable(cm)`로 빼면 **호출부의 이후 코드
  (cm.provider 접근)가 narrow를 잃어 mypy 깨진다**. 해결: `model_usable`을 `TypeGuard[ModelConfig]`로 →
  positive 분기(`if model_usable(cm):`)서 mypy가 cm을 narrow. **TypeIs는 불건전**(값-유효성 술어라 빈
  base_url 모델도 False → negative가 None 아님) — positive만 narrow하는 TypeGuard가 정확. early-return
  사이트(`if not model_usable(cm): raise`)는 TypeGuard가 negative narrow 안 해 `assert cm is not None`
  1줄 보강. → [[installed-guard-isnt-covering-guard]]

- **비밀 취급 헬퍼의 홈은 "반대 목적" 모듈을 피한다**. `llm_cfg_of`는 api_key를 **평문 복호화**하는데,
  serializers.py(마스킹된 API 출력)에 두면 "serialize=안전 반환"으로 오인될 footgun. mem_config(모델
  해석·이미 decrypt dict 조립)가 정직한 홈. 도크스트링에 "API 응답 금지" 명시. → [[structure-first-boundary-is-spec]]

- **술어 공유는 "메시지가 같을 때만"**. chat_context 기본 chat 해석은 무효 사유가 2종(등록 없음·설정
  불완전)이라 각각 다른 HTTPException 메시지 → `model_usable`로 접으면 UX 손실. 그래서 **dict 조립만
  정본화하고 술어(2 메시지)는 존치**. dedup은 본문 공유 여부지 "비슷해 보임"이 아니다(억지 통합 회피).
  → [[flow-dedup]] 계열.

## 검증 (사다리 3런)
- **단위/게이트**: metrics-fast 0. 인라인 3-키 조립 잔존 0(llm_cfg_of 정의부만)·llm_cfg_of 8 call·mypy
  narrowing 정합(TypeGuard/assert).
- **실인프라 통합**: 스위트 51/51(실패 0, flaky 1 재시도 통과) — chat 시나리오가 chat_context 핫패스,
  eval judge가 eval_runs, 메모리가 mem_config mem_cfg를 태움.
- **적대(codex)**: 여집합 7축 — dict 바이트 동일·params 보존·무효 분기 불변·llm/embedder 소스 안 뒤바뀜·
  TypeGuard 건전성·assert 정합·api_key 미누출 → **"여집합 공격 실패 — 결함 없음"**(codex가 trace
  화이트리스트까지 확인해 api_key 미누출 검증).

## 남은 것 (backlog)
- 후보 D(eval `_execute_*` 배경작업 스캐폴딩, 최대 절감이나 락 lifecycle 위험).
- eval_* 내부 중복 미전수·stale verifier 일괄 갱신.
