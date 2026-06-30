# 071 — MCP 인자·결과 redaction: 과대평가된 P0를 정직한 defense-in-depth로 재분별

스펙: `docs/spec/087-mcp-args-result-redaction.md`
관련 learning: 090(이번), [[value-secrets-need-allowlist-not-key-blocklist]]=089, [[cap-the-raw-source-not-the-buffer]]=059, [[probe-deeper-before-concluding]], [[adversarial-review-before-destructive-ship]]
선행: retrospect 070 §3(086 codex F1을 087로 분리한 그 항목)

## 무엇을 했나

086 codex 리뷰가 "MCP args/result가 trace에 원문 노출 → 비밀 누출 **P0**"로 짚어 087로 분리해둔
항목을 실행했다. MCP 도구 호출 인자(`_wrap_mcp_tool` `_execute`의 kwargs)·결과(text)가
calls_sink·`interrupt()` payload·DB 영속 `Approval.args`로 새기 *전에* 원천(runtime.py)에서
정화한다: 민감-키 blocklist redactor + budgeted 캡 + result 캡 + fail-closed.

## 무엇이 어긋났고 무엇을 배웠나

### 1. "왜 하는지 모르겠다"에서 멈춰 위협 모델을 실측했다 (probe-deeper)

사용자가 작업 도중 **"이 작업을 왜 하는 건지 모르겠습니다"**로 근거 자체를 쳤다. 나는 그때까지
codex의 "P0" 프레이밍을 *액면 그대로* 받아 밀고 있었다 — [[probe-deeper-before-concluding]]
위반. 멈춰서 한 겹 파보니 P0는 과장이었다:

- **시스템 자기 비밀은 이 표면에 안 온다.** MCP 서버 Bearer 토큰은 연결 *헤더*
  (`headers["Authorization"]`)에 있지 도구 kwargs가 아니고, 모델 api_key는 ChatOpenAI 설정이지
  도구 인자가 아니다. grep/read로 확인했다 — `api_key`·`token`이 args/result로 새는 *실재* 경로 없음.
- **표면은 인증된 admin/owner 전용**(spec 011/031/053). 공개 누출이 아니라 이미 인증된 관리자가
  자기 세션 trace를 보는 것. → "P0 누출"은 실은 **defense-in-depth 갭**.

교훈: **선행 리뷰가 매긴 심각도(P0)를 그대로 상속하지 마라.** 086 맥락에선 F1이 P0로 *보였지만*,
분리해 단독으로 위협 모델을 실측하니 등급이 내려갔다. 사용자가 근거를 치기 *전에* 내가 쳤어야 했다.

### 2. 등급을 내리되 작업을 버리진 않았다 — scope B (과한 금칠 회피)

A(드롭)/B(최소)/C(086급 full allowlist) 중 사용자가 **B**를 골랐다. defense-in-depth라고 0으로
만들지 않은 이유: 싸고 정직한 최소 처방으로 닫을 수 있다. 086급 recursive value-allowlist는
보조도구(인스펙터)에 **과한 금칠**(메모리: model/config·memory가 토대, 나머지는 과투자 금지).

### 3. 086과 polarity가 *정당하게* 다르다 (allowlist vs blocklist)

086 노드 상태 델타는 값 **allowlist**(`{plan}`만)였다 — 임의 내부 상태라 deny-by-default가 옳다.
087 MCP args는 키 **blocklist** + 평범 키 값 *보존*이다. 모순이 아니다: **args는 인스펙터의
존재이유가 "그 값을 보여주는 것"**(디버깅 가치)이라 deny-by-default를 쓰면 도구가 죽는다. 같은
"비밀 누출 0" 불변식이 표면의 *목적*에 따라 다른 처방을 부른다. 이 차이를 스펙에 명시 기록했다.

### 4. 원천 한 곳에서 닫았다 (중앙 경계, learning 065)

누출 표면이 producer 1곳(runtime.py)·끝단 3곳(Inspector·ApprovalsView·pending_trace)이었다.
끝단 3곳을 각각 고치는 대신 **sink 진입 전 원천에서 redact** — 프런트 변경 0. 끝단을 N개 고치면
새 끝단이 생길 때마다 다시 샌다.

### 5. codex가 여집합 3건을 정확히 짚었다 — 셋 다 값쌌다 (적대 리뷰)

자가 단위는 전부 초록이었지만 codex가 "보장 목록의 여집합"에서:

- **F1**: `_SENSITIVE_KEY`가 `api_key`만 봐 `private_key`·`access_key`·`*_key` 표준 비밀명 누락.
  → `[_-]key$|^key$` 추가. monkey/top_k는 구분자 없어 거짓양성 0(C1b로 잠금).
- **F2**: redactor가 float 원문 통과 → **NaN/Infinity가 JSONB(`Approval.args`)·엄격 JSON에 비유효**
  → commit이 깨진다. 표시 redaction이 *영속 경로를 깰* 뻔했다. `math.isfinite`로 안전 마커.
  C2b가 `json.dumps(allow_nan=False)`로 JSONB 호환을 단언한다.
- **F3**: rag `_record` result가 `_RESULT_CAP` 우회. → `_cap` 적용.

셋 다 happy-path 초록 뒤의 경계였다. [[adversarial-review-before-destructive-ship]] 재확인.
특히 F2는 "보안 표시 기능이 영속성을 깬다"는, 내가 안 떠올린 *측면 효과* 축이었다.

## 핵심 한 줄

선행 리뷰가 매긴 심각도를 상속하지 말고 분리된 표면에서 위협 모델을 *실측*하라 — P0가
defense-in-depth로 내려갈 수 있다. 등급이 내려가도 싸고 정직한 최소 처방으로 닫되, 표면의 *목적*이
처방의 polarity를 정한다(보여주는 게 목적인 args는 blocklist, 임의 상태는 allowlist). 그리고 표시
redactor라도 *영속 경로*(JSONB)를 깰 수 있으니 적대자에게 여집합을 시켜라.
