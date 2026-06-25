# 025 — Playground Proxy: 세션 한정 설정 오버라이드

상태: **실행 완료 + 타자 검증(codex GATE: PASS — P1 1건 수정)**
날짜: 2026-06-26
브랜치: `feat/agent-service` — **main 머지 금지**(사용자 직접 테스트)
연동: [007 실 에이전트 서비스](./007-real-agent-service.md), [009 코드 에이전트 원격 실행](./009-code-agent-remote-exec.md),
[021 Playground userId UX](./021-playground-userid-ux.md), [024 mock-llm 레지스트리 모델](./024-mock-llm-registry-model.md),
[[012-runtime-config-single-source]], [[025-seed-mock-drift-needs-migration-and-shared-constant]], [[026-mock-belongs-in-registry-not-runtime-branch]],
[[027-frontend-filter-is-not-a-backend-guard]], 회고: [[016-playground-proxy-config-override]]

## 배경 / 문제

Playground는 에이전트의 **저장된 설정 그대로** 실행한다. 두 경로가 이미 갈려 있다:
- **`source=code`** → `_remote_stream`으로 원격 엔드포인트 프록시. 모델/도구/메모리 모두 미해석
  (이미 bypass). UI는 모델(`qwen3.6-35b` 등)을 "연결됨"처럼 보여주나 로컬에선 안 쓰인다 — 오해 소지.
- **`source!=code`(web)** → 레지스트리에서 모델 해석 → `build_agent`로 실행.

web 에이전트를 "모델을 바꾸면 / 프롬프트를 손보면 / 도구를 줄이면 어떻게 도나"로 테스트하려면
지금은 **에이전트를 실제로 수정·저장**해야 한다(운영 설정 오염). 세션 한정으로 설정을 덮어
실행해 보는 수단이 없다.

## 결정 (사용자 확인)

Playground를 **"Proxy(런타임 레이어)"** 모델로 개편한다 — 새 DB 엔티티 없음, chat 실행 한 겹 추상화:

```
Playground ──► Proxy(런타임) ──► [code] : overrides 무시, 원격 그대로 bypass (설정 read-only)
                                └► [web] : cfg = {에이전트 기본} ⊕ {세션 override} 로 실행
```

- **코드 에이전트: Proxy는 bypass만.** 오버라이드 불가, 패널은 read-only("원격 실행이라 설정 변경 불가").
- **web 에이전트: 세션 한정 오버라이드.** 패널 기본값 = 에이전트 저장 설정. 사용자가 바꾸면 그
  설정대로 런타임 실행. **저장된 에이전트는 불변**(테스트용, DB `agents` 행 미변경).
- **오버라이드 범위(전체 cfg):** `model` · `temperature` · `systemPrompt`(=persona) · `mcps`(도구) ·
  `memories`(메모리 스코프) · `historyDepth`.
- **설정 변경 → 채팅 재시작.** 적용 중 대화가 진행되면 오버라이드를 바꿀 때 **새 세션으로 리셋**
  (021의 `userIdLocked` + "새 대화" 패턴 확장 — 세션 중간에 구성이 바뀌어 트레이스가 섞이는 것 방지).

## 변경

### 1. 백엔드 — `ChatRequest.overrides` + `_load_context` 병합 (`packages/api/`)

- **`schemas.py`**: `ChatRequest`에 `overrides: dict | None = None` 추가. 화이트리스트 키만 의미 —
  `{model, temperature, systemPrompt, mcps, memories, historyDepth}`. 그 외 키는 무시(서버에서 필터).
- **`chat.py` `_load_context(agent_id, session_str_id, overrides=None)`**:
  - `cfg = dict(agent.config or {})`, `persona = agent.persona` 로딩 후, **web일 때만** 병합:
    ```python
    if overrides and agent.source != "code":
        allowed = {"model", "temperature", "historyDepth", "mcps", "memories"}
        cfg.update({k: v for k, v in overrides.items() if k in allowed})
        # 비어있지 않을 때만 persona 덮어쓰기 — 빈/공백으로 저장 페르소나 지움 방지(codex P1).
        sp = overrides.get("systemPrompt")
        if isinstance(sp, str) and sp.strip():
            persona = sp
    ```
    이후 `ctx`는 병합된 `cfg`/`persona`에서 읽으므로(기존 라인 그대로) 모델 해석·메모리·MCP·
    historyDepth가 전부 오버라이드를 탄다. 코드 에이전트는 분기 진입 안 함 = bypass 보존.
  - **단일 소스 불변식([012]) 유지**: 모델은 여전히 레지스트리에서 `cfg["model"]` 이름으로만 해석.
    오버라이드는 "어떤 등록 모델 이름을 고르나"를 바꿀 뿐, 런타임에 특수분기를 넣지 않는다([026] 결).
- **`chat()` 엔드포인트**: `_load_context(agent_id, body.sessionId, body.overrides)` 로 전달.

### 2. 프런트 — Playground 오버라이드 패널 (`admin/src/playground/`)

- **오버라이드 패널**(헤더 토글 또는 좌측 슬라이드 패널). 필드는 AgentsView가 이미 편집하는 것과
  동일 소스로 미러링:
  - 모델: `listModels('chat')` 드롭다운(= mock-llm 포함 → 세션 단위로 mock 결정적 테스트 가능, 024 시너지).
  - temperature(슬라이더/숫자), systemPrompt(textarea), MCP(멀티셀렉트), 메모리 스코프(멀티셀렉트),
    historyDepth(숫자).
- **기본값 = 활성 에이전트의 저장 설정.** 에이전트 전환 시 그 에이전트 기본값으로 재초기화.
- **코드 에이전트**: 패널 비활성(read-only) + 안내문. 모델 "연결됨" 오해를 여기서 함께 해소
  ("원격 실행 — 로컬에서 이 설정은 적용되지 않음").
- **변경 → 재시작**: 오버라이드를 바꾸고 "적용(새 대화)" 하면 `resetConversation`으로 세션을 비우고
  새 세션에서 시작. 대화 진행 중에는 021처럼 잠그거나, "적용 시 새 대화로 시작" 안내 후 리셋.
- **`api.ts` `streamChat`**: `overrides` 인자 추가 → POST 바디에 실어 보냄.
- **인스펙터**: 실제 실행에 적용된 모델/오버라이드를 표기(오버라이드 적용 여부 배지) → 덮어쓴 설정이
  진짜 먹었는지 화면에서 확인(025 학습의 "화면=실제" 정합).

## 비범위

- 오버라이드를 에이전트에 **영구 저장**("이 설정으로 저장") — 테스트 전용, 세션 한정.
- **코드 에이전트 오버라이드** — bypass 유지(원격이 구성 소유).
- 별도 **Proxy 에이전트 DB 엔티티** — 런타임 레이어로 충분.
- 모델 외 **새 런타임 특수분기** — 화이트리스트 병합만, [012] 유지.

## 검증

1. web 에이전트 모델 오버라이드를 `mock-llm`으로 → MLX 없이 결정적 mock 응답. DB `agents.config`는
   **불변**(psql로 행 확인).
2. systemPrompt 오버라이드 → 응답이 새 프롬프트 반영. 바꾸면 "새 대화"로 리셋됨 확인.
3. mcps/memories/historyDepth 오버라이드가 트레이스(인스펙터)에 반영 — 도구 수·메모리 스코프·
   contextMessages 변화 확인.
4. 코드 에이전트(Doc Translator): 패널 read-only, bypass 동작 불변(원격 mock 응답 그대로).
5. 세션 한정: 다른 에이전트로 전환/새로고침 → 오버라이드가 에이전트 기본값으로 초기화.
6. tsc 무오류 + 타자 검증(codex)으로 병합 로직(코드 에이전트 bypass 보존, 화이트리스트, [012] 불변식).

## 타자 검증 (codex GATE: PASS)

`codex exec`(high)로 spec 025 병합 로직(chat.py·schemas.py·OverridePanel·api.ts·Playground)을
5개 불변식(코드 bypass / 화이트리스트 / 무회귀 / 빈 systemPrompt 보존 / 세션 한정·비영속)으로 비판 검증.

- **[P1] 수용·수정**: `_load_context`가 `overrides["systemPrompt"]==""`(빈/공백)일 때 `persona=""`로
  저장 페르소나를 덮어쓰는 결함(불변식 4). 프런트 `overridePayload`만 빈 값을 거르고 **백엔드가
  클라이언트를 신뢰**한 게 문제 — 직접 API 호출이면 persona가 날아감. 백엔드에 `isinstance(sp,str) and
  sp.strip()` 가드 추가(클라이언트 불신뢰). 라이브 재검증: 빈 override → "Paris"(persona 보존), 비어있지
  않은 override → "BANANA"(적용).
- **[P2] 정보성**: `OverridePanel.tsx`가 신규 **untracked** 파일이라 `git diff`에 안 잡혀 codex가
  `overridePayload`를 못 봄 — 결함 아님, 프런트 diff 미가시. (가드는 백엔드로 내렸으므로 안전.)

라이브 검증 6/6 PASS: ① mock-llm 모델 오버라이드 → `[mock-llm]` 결정적 응답 + DB `config.model` 불변
② 오버라이드 없을 때 실제 qwen 응답(무회귀) ③ 코드 에이전트 오버라이드 무시 → 원격 bypass 보존
④ systemPrompt 오버라이드가 실제 모델까지 도달(qwen "BANANA") ⑤ persona 컬럼 DB 불변 ⑥ 빈 systemPrompt 가드.

## 완료 조건

- [x] `ChatRequest.overrides` + `_load_context` 화이트리스트 병합(web만, code bypass 보존)
- [x] Playground 오버라이드 패널(전체 cfg, 기본값=에이전트 설정, 코드=read-only)
- [x] 변경 → 새 대화 재시작(021 패턴 확장)
- [x] `streamChat` overrides 전달 + 인스펙터 적용 표기
- [x] mock-llm 모델 오버라이드로 결정적 테스트 동작(실측) + DB 불변 확인
- [x] tsc 무오류 + 타자 검증 통과(codex GATE: PASS, P1 수정)
- [ ] **main 머지 금지**(사용자 직접 브랜치 테스트 예정)
