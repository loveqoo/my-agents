# 057 — 원격/외부 에이전트 등록을 A2A로 단일화 (provenance만 구분)

> 상태: **초안 v2(검토 반영)**. 결정 흐름: "중복 같다" → "하나로 통합(URL 자동판별)" →
> **"둘 다 A2A 아닌가?"(사용자 지적)** → **"A2A 단일화(권고·원리적)"**. 이 문서는 그 최종 방향.

## 배경 / 문제
에이전트 메뉴에 등록 진입점이 둘(`원격 에이전트 등록`·`외부 A2A 등록`)이라 사용자가 **중복**으로
느꼈다. 조사 결과 *현재 구현*은 프로토콜이 갈렸다:

| | 원격 에이전트(`code`) | 외부 A2A(`external`) |
|---|---|---|
| 등록 | `POST /agents/register`(프론트가 매니페스트 **날조**) | `POST /agents/external`(백엔드 실 카드 fetch) |
| 런타임 | `_remote_stream` — 자체 `POST {messages}`→SSE `{text}` (**A2A 아님**) | `_a2a_stream` — A2A JSON-RPC `message/stream` |

**사용자 핵심 지적**: 플랫폼 전제(CLAUDE.md *"에이전트는 A2A 프로토콜을 지원하며"*)대로면 **SDK로
만든 에이전트도 A2A를 말해야** 한다. 지금의 `_remote_stream` 자체 SSE가 오히려 예외/지름길이다.
SDK가 A2A를 내면 두 등록은 "A2A 에이전트를 카드 URL로 등록"하는 같은 일이 되고, 남는 차이는
**프로토콜이 아니라 출처(provenance)** 뿐이다.

## 결정 (A2A 단일화)
- **프로토콜 단일**: 모든 원격 에이전트는 A2A(JSON-RPC 2.0 `message/stream`). 런타임은 `_a2a_stream`
  하나. **`_remote_stream`(자체 SSE)·그 분기 폐기.**
- **source = 출처(provenance)만**:
  - `code` = **우리가 SDK로 배포한** A2A 에이전트. 카드가 my-agents 확장 메타(model/persona/mcps/
    repo/commit/versions)를 실어 1급 표시·resync 지원. 첫째 당사자.
  - `external` = **제3자** A2A 에이전트. 불투명 카드 스냅샷, 로컬 미해석.
- **등록 진입점 하나**: 백엔드가 카드를 fetch해 **확장 메타 유무로 자동분류**. 프론트 날조 제거.

## 설계

### A. 카드 확장 규약 (provenance 신호)
A2A Agent Card에 우리 네임스페이스 확장 블록을 둔다(없으면 제3자):
```json
"x-my-agents": {
  "manifest": { "model": "...", "persona": "...", "memories": [...], "mcps": [...],
                "permissions": [...], "historyDepth": 10 },
  "deploy": { "repo": "acme/x", "commit": "f3a91c2", "runtime": "my-agents-sdk · Python 2.4.1",
              "versions": [{ "version": "f3a91c2", "status": "active", "note": "..." }] }
}
```
`agent_card.py`에 `extract_my_agents(card) -> dict | None` 추가 — 확장 블록을 안전 파싱(타입 가드).
있으면 code, 없으면 external. (제3자가 흉내낼 수 있으나 provenance는 본질상 카드 자기선언 신뢰 —
플랫폼 범위에서 수용. 추후 서명 검증은 별 스펙.)

### B. 통합 엔드포인트 `POST /agents/connect`
입력 `{ url: str, token?: str }`:
1. **SSRF 가드**(`guard_url`) — 044/055.
2. `card = await agent_card.fetch_card(url)` (well-known+직접). 실패 → 400(사유 그대로).
3. `ext = agent_card.extract_my_agents(card)`.
   - `ext` 있음 → `source='code'`: config는 `ext.manifest`에서 채움(+카드 스냅샷), `ext.deploy`로
     repo/commit/runtime·`AgentVersion` 생성. **날조 없음**(전부 카드에서 fetch).
   - `ext` 없음 → `source='external'`: 기존 로직(불투명 카드 스냅샷, 로컬 빈 config).
4. `endpoint = card["url"]`(A2A 서비스 url). `live = probe_endpoint(endpoint)` → status.
5. token 있으면 `crypto.encrypt`. 저장 후 `AgentOut` 반환(source가 곧 분류 결과).
6. 둘 다 아님/도달 불가는 2의 400으로 수렴.

기존 `register_code_agent`·`register_external_agent` 공개 라우트는 **deprecated 유지**(무회귀), 내부
로직은 connect와 공유 헬퍼로. 프론트는 connect만 호출.

### C. 런타임 (chat.py)
- `ctx["source"] in ("code","external")` → **둘 다 `_a2a_stream`**. code/external 분기 제거,
  `_remote_stream` 삭제. 비로컬 게이트(`source not in (...)`로 RAG/로컬모델 skip)는 그대로.
- code의 저장 config(model/persona/mcps)는 표시용 메타 — A2A 호출엔 카드 url+token만 쓴다(현 external과 동일).

### D. 프론트 — 단일 진입점
- 버튼 둘 → **하나**: `원격 에이전트 연결`. 모달 하나(URL + 선택 토큰 + [연결]).
- `RegisterAgentModal`(code, 날조 `연결 테스트` 포함)·`RegisterExternalModal` → **하나 ConnectAgentModal**.
  구조는 기존 External 모달(URL+토큰+백엔드 위임) 재사용. 제출 → `connectAgent(url, token)`.
- 결과 토스트·배지는 반환 `source`로 도출(code→"SDK 에이전트"/external→"외부 A2A"). 상세 패널의
  source 배지·카드 표시는 유지.

### E. 픽스처 / 마이그레이션
- **mock_remote**: 제1자(SDK) A2A 픽스처 추가 — `x-my-agents` 확장을 실은 카드 + A2A JSON-RPC
  엔드포인트(기존 `/a2a` 재사용 또는 `/_remote/sdk` 신설). 기존 weather 카드(확장 없음)는 external
  분류 테스트 대상으로 유지. (045 self-fixture — connect 분류 양 분기를 결정적으로 검증.)
- **seed `Doc Translator(code)`**: endpoint를 A2A 엔드포인트로 이전, 카드에 `x-my-agents` 확장 부여.
  illustrative provenance(repo/commit/versions)는 시드 픽스처로 유지(external 카드 하드코딩과 동일 취지).
- **라이브 DB**: 기존 code 에이전트(Doc Translator) endpoint가 자체 SSE(`/_remote/agent`)를 가리키면
  A2A 폐기 후 채팅이 깨진다 → 재시드 또는 행 직접 갱신(호스트 작업, 내가 수행·승인). dry-run 후 적용.

## 완료 조건(검증)
1. **통합 테스트**(실 DB·self-cleaning):
   - `connect(SDK 확장 카드 URL)` → `source='code'`, config가 카드 manifest와 일치, versions 생성.
   - `connect(plain A2A 카드 URL)` → `source='external'`, 불투명 스냅샷.
   - `connect(루프백/사설 IP)` → SSRF 400. `connect(카드 아님/JSON 아님)` → 400.
   - **확장 파싱 견고성**: `x-my-agents`가 잡값(문자열/부분필드)이어도 안전(external 폴백 or 무시).
2. **런타임 무회귀**: code·external 둘 다 `_a2a_stream`으로 채팅 동작(mock A2A 대상). `_remote_stream`
   삭제 후에도 기존 세션·트레이스·persist 정상. 게이트(비로컬 skip) 유지.
3. **타자 적대 검증**(필수): codex — 확장 신뢰경계(제3자 위조), 두 프로브 SSRF/리다이렉트(044/055),
   카드 url이 등록 url과 다를 때(카드가 딴 host 가리킴) 검증, 폐기된 `_remote_stream` 잔재 참조.
   → **실행 완료**(codex challenge, high). 4건 발견·전부 해소(verify_057 C6~C8로 음성 인코딩):
   - **F1 SSRF(리다이렉트)**: `fetch_card`가 `follow_redirects=True`였다 — guard_url은 최초 URL만
     검사하므로 공개 카드가 302로 내부 IP를 가리켜 우회 가능(probe_endpoint·a2a_client는 이미 False).
     → `fetch_card`도 `follow_redirects=False`로 통일(C8).
   - **F2 멀티턴 회귀**: `_remote_stream`은 윈도우 히스토리를 인라인 전송했으나 `_a2a_stream`은 마지막
     메시지만·contextId 없이 보내 code 에이전트가 단턴화. → A2A 표준대로 세션 id를 `message.contextId`로
     실어 서버가 맥락 유지(C7).
   - **F3 길이 하드닝**: 빌더가 타입가드만 하고 길이 제한이 없어 잡 카드의 거대 문자열이 bounded 컬럼
     (model 120·active_version 40 등)에서 commit 500. → `_clip` 헬퍼로 컬럼 상한 절단(C6).
   - **F4 버전 불변식**: `deploy.versions=[]`인데 `active_version=commit`이라 active row 없이 포인터만
     세팅. → active row가 실재할 때만 `active_version` 세팅(C6).
4. **브라우저**(Playwright): 버튼 하나·모달 하나·연결 후 source별 토스트·목록 배지.

## 리스크 / 주의
- **런타임 폐기 = 행동 변경**: `_remote_stream` 삭제는 기존 code 에이전트 채팅 경로를 바꾼다. 시드·
  라이브 마이그레이션과 무회귀 테스트로 막는다. 마이그레이션 전 dry-run.
- **provenance 위조**: 카드 자기선언이라 제3자가 `x-my-agents`를 흉내내면 code로 보임. 1차 범위는
  수용(표시·메타 차이일 뿐 권한 상승 아님 — code/external 모두 읽기전용·로컬 미해석). 서명은 추후.
- **SSRF 표면**: connect의 fetch_card·probe_endpoint 모두 guard_url 선행·`follow_redirects=False`(044/055/
  057-F1). 세 outbound(fetch_card·probe_endpoint·a2a_client) 전부 리다이렉트 비추종으로 통일.
- **카드 url ≠ 등록 url**: 카드가 광고하는 service url을 endpoint로 쓰므로, 그 url도 guard 대상(현
  probe_endpoint가 guard. A2A 호출 시 a2a_client도 guard_url).

## 폐기/대체
- `_remote_stream`(chat.py) — 삭제.
- 프론트 `RegisterAgentModal`의 날조 `연결 테스트`(setTimeout/Math.random) — 삭제.
- `RegisterCodeAgentIn`(매니페스트 클라 입력) — connect 도입 후 deprecated(라우트는 잔존).
