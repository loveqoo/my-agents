# 026 — 외부 에이전트: A2A Agent Card 등록 (1차)

상태: **실행·검증 완료(Execution/Verification) — main 머지 보류**(사용자 직접 브랜치 테스트 예정)
날짜: 2026-06-26
브랜치: `feat/agent-service` — **main 머지 금지**(사용자 직접 테스트)
연동: [007 실 에이전트 서비스](./007-real-agent-service.md), [008 모델 레지스트리](./008-model-registry.md),
[009 코드 에이전트 원격 실행](./009-code-agent-remote-exec.md), [010 secret-at-rest](./010-secret-at-rest.md),
[025 Playground Proxy 오버라이드](./025-playground-proxy-config-override.md),
[[014-secret-at-rest-fernet]], [[026-mock-belongs-in-registry-not-runtime-branch]],
[[agent-source-three-way-a2a-external]], [[why-build-multi-agent-platform]]

## 배경 / 문제

이 프로젝트의 목적은 **다양한 에이전트를 쉽게 만들고 계속 재사용하며 A2A로 협업**시키는 것
([[why-build-multi-agent-platform]]). 지금은 에이전트를 **내가** 만드는 두 경로만 있다:
`source=ui`(웹설정, 로컬 `build_agent` 실행) / `source=code`(하드코딩, 원격 bypass).
**남이 만든 A2A 에이전트를 내 생태계에 편입**시키는 경로가 없다 — "모은다"의 범위가 내가 만든
것에 갇혀 있다.

A2A 에이전트는 **Agent Card**(예 `/.well-known/agent.json`)로 자기 capabilities·skills·엔드포인트·
인증을 광고한다. 카드 URL만 가리키면 등록·검증·표시가 가능하다.

## 비범위 (→ 2차 스펙)

**이 스펙은 등록·표시·플레이그라운드 취급까지만.** 외부 에이전트를 실제로 **호출해 응답을 받는
A2A 런타임은 2차**(별도 스펙)로 뗀다. 이유: code의 bypass(`_remote_stream`)는 `{messages}`+Bearer+
SSE`{text}` 포맷이라 **A2A(JSON-RPC `message/send` + SSE) 클라이언트로 재사용 불가** — 새 전송
계층은 독립적으로 클 만큼 크다. 단계를 섞으면 1차가 늦어진다.

- 외부 에이전트 채팅 실제 응답(A2A 호출) — 2차.
- 외부 에이전트의 상세 트레이스(원격 메모리/MCP) 수집 — 2차.
- 카드 자동 갱신/주기적 재검증 — 추후(1차는 등록 시점 스냅샷).

## 알려진 한계 (→ 2차 보강)

- **SSRF**: `fetch_card`가 admin이 준 URL을 **서버에서 그대로 GET**한다. 내부망 주소(예 `169.254`
  메타데이터, 사내 서비스)를 찌를 수 있는 SSRF 표면. 1차는 **admin 인증 전용 엔드포인트**(신뢰
  경계 안)라 보류하고, dev mock 카드가 `127.0.0.1`을 일부러 가리키므로 사설/loopback 대역을 막으면
  자체 테스트가 깨진다. **실제 outbound 호출은 2차 A2A 런타임에서 일어나니, 사설대역 차단·egress
  정책은 그때 함께 다룬다.** (codex GATE 지적 — 사용자 합의로 phase 2 이관, 2026-06-26.)

## 결정 (3분기 source)

`source`를 **2분기 → 3분기**로 확장:

| source | 정체 | 실행 | 등록 |
|---|---|---|---|
| `ui`(웹설정) | 어드민서 구성 | 로컬 `build_agent` | UI 입력 |
| `code`(하드코딩) | 코드로 정의 | 원격 bypass(`_remote_stream`) | 코드 배포 |
| **`external`(외부)** | 남의 A2A 에이전트 | **A2A 클라이언트(2차)** | **카드 확인 후 등록** |

- **외부=`code`와 같은 "비로컬" 취급**: 로컬 모델/메모리/MCP 미해석. 단 하드코딩 엔드포인트가
  아니라 **카드로 발견**된다는 점이 다름.
- **`exposed:{a2a}`(서버측 노출)와 방향 반대**: external은 우리가 **클라이언트(소비측)**.

## 변경

### 1. 백엔드 — Agent Card 등록·저장 (`packages/api/`)

- **`models.py`**: `Agent.source` 주석 `ui | code` → `ui | code | external`(컬럼 타입 변경 없음,
  String(20) 그대로). 외부 메타 저장은 **기존 컬럼 재사용 + config JSONB**:
  - `endpoint` = 카드가 광고한 A2A 서비스 URL.
  - `token` = 외부 호출 크레덴셜. **코드 에이전트의 마스킹과 달리 `crypto.encrypt`로 암호화 저장**
    (2차에서 실제 호출에 복호 필요 — [010]/[[014-secret-at-rest-fernet]]). 카드가 인증 불요면 null.
  - `config["card"]` = 등록 시점 fetch한 **카드 원본 JSON 스냅샷**(capabilities·skills·version·
    provider 등). 표시·검증의 단일 소스.
- **`agent_card.py`(신규 모듈)**: A2A 카드 fetch·검증.
  - `fetch_card(url) -> dict`: httpx로 카드 URL GET. URL이 카드 문서가 아니라 베이스면
    `/.well-known/agent.json` 관례 시도.
  - `validate_card(card)`: 필수 필드(`name`, 서비스 `url`, `capabilities`(객체)/`skills`(배열)) 존재·
    **타입**까지 검증(`"skills":"x"` 같은 잡값 거부). 실패 시 명확한 에러(어느 필드가 빠졌나).
  - **응답 크기 상한**: 카드 본문을 스트리밍으로 읽어 256KB 초과 시 중단(악성/오작동 서버의
    메모리·시간 소진 방지). codex GATE 반영.
- **등록 API**(`agents` 라우터): `POST /agents/external` body `{cardUrl, token?}` →
  fetch+validate → `Agent(source="external", agent_id="agt_"+..., name=card.name, endpoint=card.url,
  token=encrypt(token) if token, config={"card": card})` 생성. 검증 실패는 4xx + 사유.
- **`chat.py` 게이트 3분기화**:
  - L47 override 게이트: `source != "code"` → `source not in ("code", "external")`
    (외부도 오버라이드 불가).
  - L73 로컬 모델해석 게이트: 동일하게 외부 제외(로컬 모델 미해석).
  - 런타임 분기(L283): **1차에서는 외부 채팅을 호출하지 않는다.** `source=="external"`면
    "A2A 런타임 미구현(2차 예정)" 안내를 SSE로 1프레임 반환하고 종료(크래시·로컬 폴백 금지).
    [026] 결대로 런타임 특수분기는 최소 — 데이터(source)로만 가른다.

### 2. 프런트 — 외부 등록 UI + 카드 표시 (`admin/`)

- **`AgentsView.tsx`**: "외부 에이전트 추가"(카드 URL + 선택 토큰) 폼 → `POST /agents/external`.
  목록/상세에 **source 배지 3종**(웹설정/코드/외부) 표시(기존 UI vs Code 배지 확장, 핸드오프2 계승).
- **카드 정보 패널(읽기 전용)**: 등록된 외부 에이전트의 `config.card`에서 capabilities·skills·
  엔드포인트·version·provider를 표시. "남이 소유 — 여기서 수정 불가" 안내.
- **`OverridePanel.tsx`(플레이그라운드)**: 외부를 **코드처럼 read-only** 처리(게이트 확장).
  카드 정보를 같이 노출. 인스펙터/시스템프롬프트 뷰어에 "외부(A2A) — 로컬 설정 미적용".

### 3. 시드/마이그레이션

- **마이그레이션**: 컬럼 추가 없음(기존 컬럼+config 재사용) → **스키마 마이그레이션 불필요**.
  데이터 마이그레이션도 불필요(신규 source 값일 뿐).
- **시드(선택)**: 동작 확인용 **로컬 mock A2A 카드**를 하나 둘지 검토 — `mock_remote.py`에
  `/.well-known/agent.json` 류 더블 추가(009의 self-call 데모 패턴 계승). 1차 검증 편의용, opt-in.

## 검증

1. mock 카드 URL로 `POST /agents/external` → 외부 에이전트 등록. DB에 `source="external"`,
   `endpoint`=카드 url, `config.card`=스냅샷, `token`=암호문(토큰 줬을 때) 확인(psql).
2. 잘못된 카드(필수 필드 누락/404) → 4xx + 명확한 사유, 행 미생성.
3. 어드민 목록에 외부 배지 + 카드 정보 패널(capabilities/skills) 읽기전용 표시.
4. 플레이그라운드에서 외부 에이전트 선택 → OverridePanel **read-only**(코드와 동일), 카드 정보 노출.
5. 외부 에이전트 채팅 시도 → "A2A 런타임 2차 예정" 안내 1프레임(크래시·로컬 폴백 없음).
6. **무회귀**: ui/code 에이전트 등록·실행·플레이그라운드 모두 기존과 동일(게이트 3분기화가
   기존 두 분기 동작을 안 바꿈). tsc 무오류 + 타자 검증(codex)으로 게이트·등록·암호화 검증.

## 완료 조건

- [x] `source` 3분기(`external`) + 카드 fetch/validate 모듈 + `POST /agents/external` 등록
- [x] 외부 호출 크레덴셜 `crypto.encrypt` at-rest 저장(카드 스냅샷은 `config.card`) — DB에서 Fernet
      암호문(`gAAAAAB…`, 120자) 확인, 출력은 마스킹
- [x] `chat.py` 게이트 3분기화(외부=오버라이드/로컬해석 제외) + 외부 채팅은 "2차 예정" 안내 1프레임
- [x] 어드민 외부 등록 폼 + source 배지 3종 + 카드 정보 read-only 패널(`ExternalAgentDetail`)
- [x] 플레이그라운드 외부=read-only(코드와 동일) + 카드 노출(`ExternalCardInfo`)
- [x] 무회귀(ui/code 불변, 라이브 확인) + tsc 무오류 + 타자 검증(codex GATE) — 카드검증·크기상한 보강
- [ ] **main 머지 금지**(사용자 직접 브랜치 테스트 예정)
- [ ] 2차(A2A 런타임 호출) 스펙은 별도 — 본 스펙 비범위
- [ ] (2차) SSRF 사설대역 차단·egress 정책 — 위 "알려진 한계" 참조
