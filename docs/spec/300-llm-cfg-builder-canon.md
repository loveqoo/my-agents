# 300 — llm_cfg 빌더 정본화: ModelConfig → 연결 cfg 단일화 (전체 원자)

## 배경

census(deep-reasoner) 후보 C. `{base_url, api_key: crypto.decrypt(...), model_id}` 조립이 반복.
**census-lens 재적용** — census는 eval 3곳으로 스코프했으나 전역 전수하니 **동일 3-키 원자가 8곳**에 산다:
- eval 3곳(eval_runs·eval_authoring·eval_guards) — 3-키 바이트 동일
- chat_context 2곳(`_chat_model_cfg`·기본 chat 해석) — 4-키(3-키 + `params`), core 동일 (**라이브 chat 핫패스**)
- chat_context `_resolve_mem_cfg` embedder + mem_config `_build_mem_cfg`(llm·embedder) — 중첩 서브딕트가 3-키 shape

사용자 결정(AskUserQuestion): **전체 원자 편입**(whole-fix, 핫패스 포함, 검증 사다리 엄격히).

## 설계

**홈 = mem_config.py**(crypto·ModelConfig 보유, `_default_chat_model`·`_build_mem_cfg`가 이미 여기; 순환 없음
— mem_config는 sqlalchemy/crypto/models만 의존). **serializers.py 아님** — `llm_cfg_of`는 api_key를 **평문
복호화**하므로 마스킹된 API 출력 모듈에 두면 footgun.

```python
def model_usable(cm: ModelConfig | None) -> TypeGuard[ModelConfig]:
    """기본 chat/embedding 모델이 실사용 가능한가 — provider·base_url·model_id 완비(정본, 스펙 300).
    TypeGuard: positive 분기(`if model_usable(cm):`)서 mypy가 cm을 ModelConfig로 narrow(연결 dict 조립부)."""
    return (cm is not None and cm.provider is not None
            and bool(cm.provider.base_url) and bool(cm.model_id))

def llm_cfg_of(cm: ModelConfig) -> dict:
    """ModelConfig → LLM 연결 cfg(정본, 스펙 300). **api_key 평문 복호화** — API 응답 금지(런타임 구성용).
    model_usable로 검증 후 호출(내부 assert가 provider 보장 = 호출 전제 문서화)."""
    assert cm.provider is not None  # model_usable 검증 후 호출 전제
    return {"base_url": cm.provider.base_url,
            "api_key": crypto.decrypt(cm.provider.api_key), "model_id": cm.model_id}
```

**TypeGuard 선택 이유**: `model_usable`은 값-유효성 체크(None 아님 + 필드 완비)라 **TypeIs는 불건전**
(빈 base_url인 ModelConfig도 False → negative가 None 아님). TypeGuard는 positive 분기만 narrow해 건전.
positive 분기 사이트(eval_runs·mem_config·chat_context `_chat_model_cfg`)는 무-assert로 깔끔, early-return
사이트(eval_guards·eval_authoring)는 `assert cm is not None` 1줄로 보강(TypeGuard는 negative narrow 안 함).

## 사이트별 처리 (8곳, 무효 분기는 호출자별 존치 — 스펙 268)

1. **eval_runs**(positive): `if model_usable(_cm): judge_llm = llm_cfg_of(_cm)`.
2. **mem_config `_build_mem_cfg`**(positive): `if model_usable(chat_m) and model_usable(emb_m): return
   {"llm": llm_cfg_of(chat_m), "embedder": llm_cfg_of(emb_m)}` / else None. cp·ep 지역변수 제거.
3. **chat_context `_chat_model_cfg`**(positive 반전): `if model_usable(m): return {**llm_cfg_of(m),
   "params": dict(m.params or {})}` / else None.
4. **chat_context 기본 chat 해석**(커스텀 메시지 2종 존치): `if m is None: raise(등록된 모델 없음)` +
   `if not base_url or not m.model_id: raise(설정 불완전)` 그대로 두고, 마지막 dict만 `{**llm_cfg_of(m),
   "params": ...}`. **술어 미공유**(두 에러 메시지가 달라 model_usable로 접으면 UX 손실).
5. **eval_guards `_helper_llm`**(early-return + is_mock 2차 체크): `if not model_usable(cm): return None,
   "없음"; assert cm is not None and cm.provider is not None; if is_mock_llm(...): return None, "mock";
   return llm_cfg_of(cm), None`.
6. **eval_authoring `_execute_generation`**(early-return raise): `if not model_usable(cm): raise
   RuntimeError; assert cm is not None; llm_cfg = llm_cfg_of(cm)`.

호출자 인라인 `from . import crypto`는 dedup 후 미사용이면 제거(ruff F401).

## 목표 (측정 가능)
1. `mem_config.model_usable`·`llm_cfg_of` 신설. 3-키 `{base_url, api_key: decrypt, model_id}` 인라인 조립
   잔존 0(견고 grep). llm_cfg_of 호출 = 편입 사이트 수.
2. **행위 보존**: 각 사이트의 무효 분기(raise/None/None+reason/is_mock·커스텀 메시지 2종) 불변. 핫패스
   (chat_context) 모델 해석 결과 dict 바이트 동일(4-키 포함).

## 검증 (사다리 3런)
- **단위/게이트**: metrics-fast 0(mypy narrowing 특히 — TypeGuard/assert 정합). 인라인 3-키 조립 잔존 0.
- **실인프라 통합**: 스위트 51/51(chat 시나리오가 chat_context 핫패스·eval judge·mem0 mem_cfg 다 태움).
  verify_142/143/195(eval 출제)·메모리 관련 verifier.
- **적대(codex)**: 여집합 — (a) 3-키 dict 바이트 동일(키 순서·decrypt 대상 동일)? (b) chat_context 4-키가
  params 보존? (c) 각 무효 분기 메시지·타입(raise/None/tuple) 불변? (d) mem_config llm/embedder 소스가 올바른
  ModelConfig(chat_m↔llm, emb_m↔embedder 안 뒤바뀜)? (e) TypeGuard 건전성(빈 필드 모델 오narrow 없나)?

## OUT
- chat_context `_resolve_mem_cfg`의 llm 서브딕트(이미 만든 model_cfg dict에서 3키 projection) — ModelConfig가
  아닌 dict→dict라 llm_cfg_of(ModelConfig) 원자와 다른 연산, 무변경(embedder 서브딕트만 llm_cfg_of(emb)).
- 후보 D(eval 배경작업 스캐폴딩) — 별도 스펙.
