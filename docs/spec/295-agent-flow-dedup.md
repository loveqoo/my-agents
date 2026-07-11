# 295 — 에이전트 flow 중복 제거: 모델 빌더·사용자텍스트 정본화

## 배경

사용자가 agent 패키지서 복붙 중복을 직접 적발(2026-07-11). 앞선 "조립 누출" 전수가 정의를 좁게 잡아
놓친 것. 넓힌 전수(deep-reasoner)로 B 8건 확인 — 그중 가장 명확한 **agent flow 중복 2종**부터.

**측정된 중복(본문 diff 근거):**
- `_model_from_cfg`(ChatOpenAI 구성) = route·orchestrate·plan_execute **바이트 동일** + 변형 3
  (artifact `_make_model`=None허용·temp 0.2, pipeline `_model_from_node`=cfg 노드폴백·에러문구,
  main.py build_agent 인라인 블록) = **6중 복제**. 도크스트링이 "동일 규칙"이라 상호참조로 자백.
- `_last_user_text` = route·orchestrate 바이트 동일, artifact는 role 필터(`role in ("human","user",None)`) 변형.

## 목표 (측정 가능)

1. **정본 1개씩**:
   - `agent/model.py` 신설 — `build_chat_openai(cfg, params, *, default_temperature=0.7,
     on_missing="raise"|"none", error_label=...)`. cfg 출처·None허용·기본temp·에러문구를 **파라미터화**
     (차이 지점만 인자로). 6 복제의 구성 블록을 단일화.
   - `toolbox.py`에 `last_user_text(state, roles=None)` — roles=None이면 필터 없음(route/orchestrate
     현행), roles 지정 시 그 role만(artifact 현행). 3 복제 단일화.
2. **복제 블록 삭제·구성 집중**: `ChatOpenAI(...)` 구성 블록이 `model.py` **단일**(측정:
   `grep "ChatOpenAI(" packages/agent/src` 중 model.py 외 = **0**). `_model_from_cfg`·`_make_model`·
   `_last_user_text` 로컬 def = **0**. 단, `pipeline._model_from_node`는 **얇은 어댑터로 존치**
   (노드 cfg 폴백 + 몽키패치 시임 verify_260/261/268/270) — 구성 블록은 빠지고 `build_chat_openai`에
   위임하므로 중복(구성)은 제거됨, pipeline 고유 글루만 남음.
3. **행위 보존(바이트 동일)**: 각 사이트의 관측 동작 불변 — 파라미터화로 온도·None·에러문구·role필터가
   기존과 정확히 일치. 측정: verify_041(기본)·102(orchestrate)·route/pipeline/artifact 관련 verify +
   실모델 스위트 51/51.

## 설계

### build_chat_openai (agent/model.py)
```python
def build_chat_openai(cfg, params=None, *, default_temperature=0.7,
                      on_missing="raise", error_label="모델 설정이 필요합니다 ...") -> ChatOpenAI | None:
    cfg = cfg or {}; base_url = cfg.get("base_url") or ""; model_id = cfg.get("model_id") or ""
    if not base_url or not model_id:
        if on_missing == "none": return None
        raise RuntimeError(error_label)
    cfg_params = cfg.get("params") or {}; params = params or {}
    temperature = params.get("temperature", cfg_params.get("temperature", default_temperature))
    return ChatOpenAI(base_url=base_url, api_key=cfg.get("api_key") or "sk-noauth", model=model_id,
        temperature=temperature,
        extra_body={"chat_template_kwargs": {"enable_thinking": cfg_params.get("enable_thinking", False)}})
```
- 호출부(차이만 인자로):
  - route/orchestrate/plan_execute: `build_chat_openai(ctx.model_cfg, ctx.params)` (기본값 그대로).
  - main.py build_agent: 동일 `build_chat_openai(cfg, params)`.
  - artifact `_make_model`: `build_chat_openai(ctx.model_cfg, ctx.params, default_temperature=0.2, on_missing="none")`.
  - pipeline `_model_from_node`: `build_chat_openai(node.get("model_cfg") or ctx.model_cfg, ctx.params,
    error_label="노드 모델 설정이 필요합니다 (base_url/model_id) — 모델을 등록하세요.")`.
- `ChatOpenAI`는 model.py 최상위 import(route/orchestrate/plan_execute/pipeline/main 다 top-level).
  artifact의 지연 import는 미세최적화였으나 어차피 다른 flow가 import → 실질 비용 0.
- model.py는 langchain_openai만 의존(ctx 타입 미의존) → 순환 없음.

### last_user_text (toolbox.py, `_first_line` 이웃)
```python
def last_user_text(state, roles=None) -> str:
    for msg in reversed(state["messages"]):
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict): content = msg.get("content")
        if roles is not None:
            role = getattr(msg, "type", None) or (msg.get("role") if isinstance(msg, dict) else None)
            if role not in roles: continue
        if content: return content if isinstance(content, str) else str(content)
    return ""
```
- route/orchestrate: `last_user_text(state)`. artifact: `last_user_text(state, roles=("human","user",None))`.
- toolbox는 flows/examples가 이미 import(순환 안전 — toolbox는 runtime/flows 미의존).

## 검증
- 행위 보존: verify_041(기본 에이전트)·102(orchestrate 전략)·route/pipeline/artifact 관련 verify + 스위트 51/51.
- 수치: 로컬 def 6+3 → 0(grep), model.py/toolbox 정본 각 1, `make metrics-fast`(ruff/mypy 0).
- import 스모크: 각 flow 모듈 + `_bootstrap_builtins` 등록 8개 정상.

## OUT
- route/pipeline/plan_execute의 `build_graph` 그래프 위상은 **각자 다름 = 정당**(공통 베이스 억지 금지, 스펙 268 교훈).
- describe/AgentManifest 내용은 에이전트별 상이 = 중복 아님.
- 다른 B(api A2A 프레이밍·get-or-404·authz 등)는 스펙 296+ 별도.
