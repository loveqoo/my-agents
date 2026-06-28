# 046 — 원격 에이전트를 A2A로 단일화: source를 출처(provenance)로 강등 회고

> 스펙 057. 결정 흐름: "등록 진입점 둘이 중복" → "URL 자동판별로 통합" →
> **사용자 지적 "둘 다 A2A 아닌가?"** → **A2A 단일화**(자체 SSE `_remote_stream` 폐기,
> `source`는 프로토콜이 아니라 출처만 구분: code=우리가 SDK로 배포한 1급 / external=제3자 불투명).

## 무엇을 했나
- **프로토콜 단일화**: 모든 원격 에이전트가 A2A(JSON-RPC 2.0 `message/stream`)를 말한다. 런타임은
  `_a2a_stream` 하나. 자체 SSE `_remote_stream`(프론트가 매니페스트 날조 → `POST {messages}` → SSE
  `{text}`)와 그 분기를 **삭제**.
- **source = provenance만**: 카드의 `x-my-agents` 확장 유무로 자동분류 — 있으면 `code`(manifest·deploy
  메타로 1급 표시·버전 생성), 없으면 `external`(불투명 카드 스냅샷). `agent_card.extract_my_agents(card)`가
  타입가드하며 dict→code / None→external.
- **등록 진입점 하나** `POST /agents/connect`: SSRF 가드 → `fetch_card` → `extract_my_agents` →
  code/external 빌더. 프론트 날조 제거(전부 카드에서 fetch).
- **라이브 마이그레이션**: 시드된 `Doc Translator(agt_xlt_a17c33)`가 폐기 endpoint(`/_remote/agent`)·
  카드 없음이라 `_remote_stream` 삭제 후 채팅이 깨졌다 → dry-run·승인 후 단일 행을 A2A endpoint
  (`/_remote/a2a`) + seed 동형 `x-my-agents` 카드로 갱신. 라이브 채팅 스모크로 `a2a:true,remote:true`
  확인(검증 사다리 rung2).

## 무엇이 어긋났고 무엇을 배웠나
**핵심: 통합은 폐기 경로의 행동을 자동 승계하지 않는다.** 두 경로(`_remote_stream`·`_a2a_stream`)를
하나로 합칠 때, 살아남는 경로가 happy-path는 통과해도 폐기 경로가 *고유하게* 들고 있던 행동을 잃는다.
codex 적대 리뷰(rung3, 필수)가 자가테스트가 못 본 4건을 적발:

- **F2 멀티턴 회귀(이 스펙의 표본)**: `_remote_stream`은 윈도우 히스토리를 인라인 전송했으나
  `_a2a_stream`은 마지막 메시지만·`contextId` 없이 보내 code 에이전트가 단턴화. 컴파일·단턴 채팅은
  초록이라 자가검증이 구조적으로 못 봄. → A2A 표준대로 세션 id를 `message.contextId`로 실어 서버가
  맥락 유지(C7). **이게 새 learning 060의 근거**(통합 시 폐기 경로의 행동 집합을 *열거*해야 함).
- **F1 리다이렉트-SSRF**: `fetch_card`가 `follow_redirects=True`였다 — guard_url은 최초 URL만 검사하니
  공개 카드가 302로 내부 IP를 가리켜 우회 가능(probe_endpoint·a2a_client는 이미 False). → `fetch_card`도
  `follow_redirects=False`로 통일(C8). learning 055(새 아웃바운드 경로는 가드 자동상속 안 함) 재확인 —
  여기선 *기존* 경로의 기본값이 위험했던 변종.
- **F3 길이 하드닝**: 빌더가 타입가드만 하고 길이 제한 없어 잡 카드의 거대 문자열이 bounded 컬럼
  (model 120·active_version 40)에서 commit 500. → `_clip` 헬퍼로 컬럼 상한 절단(C6).
- **F4 버전 불변식**: `deploy.versions=[]`인데 `active_version=commit`이라 active row 없이 포인터만
  세팅. → active row 실재 시에만 `active_version` 세팅(C6).

4건 전부 음성 인코딩(verify_057 C6~C8, 43 check PASS). 무회귀: verify_042(44)·verify_045(7군).

**둘째 통찰(provenance vs protocol)**: 사용자의 "둘 다 A2A 아닌가?" 한 마디가 분류 축을 *프로토콜*에서
*출처*로 바꿔, "중복 진입점 둘"이 "같은 일(A2A 카드 등록)의 출처 차이"로 수렴했다. 중복으로 *느껴진*
것의 뿌리는 UI가 아니라 프로토콜 분기였고, 진짜 차이는 출처뿐이었다. 코드를 합치기 전에 "이 둘이
같은 일인가"를 프로토콜 수준에서 다시 물어야 했다.

**셋째(seed drift, rung2)**: 코드가 옳아도 *옛 체제로 영속된 데이터*(시드 행)는 깨진 채 남는다. 단위
테스트는 새로 만든 객체만 밟아 못 봄 — 라이브 채팅 통합(rung2)만이 시드 endpoint drift를 잡는다.
learning 059(거짓말의 출처를 고친다)·verification-ladder 재확인.

## 절차 메모
- 비가역 라이브 DB 쓰기 1건은 dry-run → 사용자 승인 → apply → 멱등 재확인 → 라이브 스모크 순으로
  분리(memory: adversarial-review-before-destructive-ship / user-is-remote-do-host-actions-yourself).
- 마이그레이션 스크립트는 seed 상수(`CHAT_MODEL_NAME`·`MOCK_MCP_SERVER_NAME`)를 재사용해 카드를
  seed와 *동형*으로 빌드 — 별도 하드코딩이면 다음 재시드 때 또 갈린다.
