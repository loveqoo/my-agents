# 017 — 외부 에이전트: A2A Agent Card 등록 1차 (회고)

스펙: [026](../../docs/spec/026-external-agent-a2a-card-registration.md)
날짜: 2026-06-26
연결: [[028-server-side-url-fetch-is-security-surface]], [[027-frontend-filter-is-not-a-backend-guard]],
[[026-mock-belongs-in-registry-not-runtime-branch]], [[agent-source-three-way-a2a-external]],
[009] 코드 bypass, [025] 게이트 확장

## 무엇을 했나

`source`를 2분기(`ui`/`code`)에서 3분기(`+external`)로 확장. 외부 A2A 에이전트를 **카드 URL만 받아
fetch·검증 후 등록**하는 경로를 추가했다(1차: 등록·표시·플레이그라운드 read-only 취급까지). 실제 A2A
런타임 호출은 2차로 명시 분리 — code의 bypass(`{messages}`+Bearer+SSE`{text}`)는 A2A(JSON-RPC
`message/send`)와 포맷이 달라 재사용 불가하기 때문. 새 모듈 `agent_card.py`(fetch/validate), 엔드포인트
`POST /agents/external`, `chat.py` 게이트 3분기화 + 외부 채팅 "2차 예정" 안내 1프레임. 프런트는 외부
등록 폼 + source 배지 3종 + 카드 read-only 패널(`ExternalAgentDetail`/`ExternalCardInfo`).

## 잘된 것 — 분기 대신 데이터로, 단계는 전송계층 경계로 갈랐다

- **런타임 특수분기 최소화([026] 계승.** 게이트를 `!= "code"` → `not in ("code","external")` 한 줄
  확장 + 외부 채팅 분기 하나로 끝. 외부도 code처럼 `model_cfg=None`/`mem_cfg=None`을 타서
  `_load_context`가 크래시 없이 완주(라이브 확인). 새 source는 "데이터값"일 뿐 새 경로가 아니다.
- **단계 분리 기준이 명확했다.** 1차/2차 경계를 "전송계층이 다른가"로 그었다 — 등록(카드 메타)은
  지금, 호출(A2A 클라이언트)은 별도. 덕분에 UI는 완성하고 런타임은 안내 프레임으로 미뤄도
  사용자에게 일관됐다. 마이그레이션 0(기존 컬럼 endpoint/token + config.card 재사용).
- **크레덴셜 방향을 구분했다.** code는 마스킹(표시용), external은 `crypto.encrypt`(2차에서 복호해
  실제 호출). DB에서 Fernet 암호문(`gAAAAAB…`, 120자) 확인, 출력은 마스킹 — 같은 token 컬럼이지만
  의미가 다르다는 걸 저장 형태로 구현.

## 아팠던 것 — "보조도구"라도 서버측 URL fetch는 보안 표면 (codex GATE)

외부 카드 등록을 "auxiliary, 가볍게"로 시작했는데, codex GATE가 `agent_card.py`에서 3건을 FAIL로
찔렀다:

1. **응답 크기 무제한** — `resp.json()`이 본문을 통째 버퍼. 악성 서버가 거대 JSON을 흘리면 메모리·시간
   소진. → 스트리밍으로 256KB 상한.
2. **`validate_card` 타입 미검증** — `"skills":"x"`(문자열)가 truthy라 통과. → capabilities는 dict,
   skills는 list로 타입까지 검증.
3. **SSRF** — admin이 준 URL을 서버가 그대로 GET → 내부망(`169.254` 메타데이터 등) 접근 가능.

핵심 깨달음: **1·2는 "명백한 개선"(공짜·트레이드오프 없음)이라 즉시 고쳤고, 3은 "진짜 트레이드오프"**
(사설대역 차단 시 dev mock의 `127.0.0.1`이 깨짐)라 사용자에게 올려 phase 2 이관 합의를 받았다. codex
지적을 일괄 "고친다/무시한다"로 처리하지 않고 **공짜 수정과 결정사안을 갈라낸** 게 맞았다. [[probe-
deeper-before-concluding]]의 반대 방향 적용 — 자가 단정도, 타자 지적의 무비판 수용도 둘 다 피한다.

## 다음에

- 2차 A2A 런타임(JSON-RPC `message/send` + SSE) 클라이언트는 독립 스펙. 그때 SSRF 사설대역 차단·egress
  정책을 outbound 호출과 함께 다룬다(1차 등록 fetch도 같은 가드로 묶을 수 있음).
- 서버가 외부 URL을 fetch하는 신규 기능은 시작부터 [[028-server-side-url-fetch-is-security-surface]]를
  체크리스트로 켠다 — 크기 상한/타임아웃/스킴·타입 검증은 기본값, SSRF는 신뢰경계 판단.
