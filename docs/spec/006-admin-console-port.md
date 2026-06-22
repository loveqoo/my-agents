# 006 — Admin 콘솔 + Playground 이식 (Ant Design X handoff)

상태: **구현됨 (1차) — 전 뷰 mock 이식 완료, 실 백엔드 연결은 이후 루프**
날짜: 2026-06-21 (구현 2026-06-22)
연동/확장: [003 admin web UI](./003-admin-web-ui-chat.md), [005 antd-x chat](./005-antdx-chat-refactor.md)
디자인 명세: claude.ai/design handoff 번들 (`Ant Design System-handoff.zip` → `.dev/design-refs/`)

> claude.ai/design이 우리 `my-agents`를 읽고 만든 handoff 번들의 **admin 콘솔(5뷰) + Playground(agent-debug)** 를
> **진짜 antd 6 + @ant-design/x로 재현(A 방식)** 한다. mock으로 깔고, 개발하면서 점진적으로 실제 백엔드로 채운다.

---

## 1. 목표 / 비범위

### 목표
- handoff 디자인을 **디자인 명세**로 삼아, 우리 스택(React+TS+antd 6+antd-x)으로 **픽셀에 가깝게 재현**.
- admin 콘솔: 사이더 + 헤더 + 5뷰(개요·에이전트·빌딩블록·세션·승인) + Playground.
- **Agents 뷰는 우리 백엔드로 실 CRUD**, 나머지는 mock으로 시작.
- 기존 채팅(persona+chat 실동작)을 **Playground**에 연결.

### 비범위 (이 스펙)
- `_ds_bundle.js`(번들의 자체구현 컴포넌트) **직접 사용 안 함** — 디자인 참조로만. 우리는 진짜 antd 6/antd-x 사용.
- 백엔드 신규 기능의 **실제 실행**(메모리·MCP 호출·A2A·권한·세션·승인·버저닝) — 이번엔 UI/mock만. 실제화는 이후 루프들.
- URL 라우팅(react-router) — 뷰 전환은 프로토타입처럼 내부 상태로(필요해지면 추후).

---

## 2. 결정 요약 (초안)

| 항목 | 결정 |
|---|---|
| 이식 방식 | **A — 진짜 antd 6/antd-x로 재현** (프로토타입은 명세) |
| 컴포넌트 매핑 | 번들 커스텀 API → antd 6/antd-x API (`Icon name=`→`@ant-design/icons`, `Button iconName=`→`icon`, `Menu items` 등) |
| 토큰/스타일 | 번들 `tokens/*.css`·`styles.css`의 핵심 CSS 변수를 가져와 정의 + antd `ConfigProvider` 기본 테마 |
| 뷰 전환 | AdminShell 내부 상태(프로토타입 방식), 라우터 없음 |
| 데이터 | **(변경) 전 뷰 mock으로 일괄 이식** — 사용자 결정: "각 메뉴 상세 기능 모두 옮겨줘. mock이어도 의도한 것." Agents도 현재 in-memory mock CRUD(`ADMIN_AGENTS`), 실 백엔드 연결은 이후 루프 |
| Agents 저장 | 풍부한 구성을 **`params`(jsonb)** 에 저장하는 실 백엔드 배선은 **이후 루프로 연기**. 이번엔 번들의 mock CRUD(생성/편집/삭제/버저닝/공개)를 그대로 재현 |
| Playground | **(변경) agent-debug 3분할을 mock으로 이식** — 에이전트 피커 + 가짜 스트리밍 디버그 채팅 + 턴 인스펙터 + HIL 승인 카드 + A2UI 생성형 UI. 실 백엔드 채팅(005)은 `components/Chat.tsx`에 보존, `runAgent()`를 실 스트림으로 교체하는 것은 이후 |

---

## 3. 구조 (목표)

```
admin/src/
  App.tsx                 # ConfigProvider(테마) + AdminShell 마운트
  theme.css               # 번들 토큰에서 가져온 CSS 변수
  admin/
    AdminShell.tsx        # 사이더 + 헤더 + 뷰 라우터(상태)
    shared.tsx            # Page, StatusPill, Panel, Table, Drawer, Desc, VersionHistory, ExposeSwitch (antd 6 재현)
    mockData.ts           # BLOCKS, ADMIN_AGENTS(초기), SESSIONS, APPROVALS, 상태맵 (디자인 데모 데이터)
    views/
      OverviewView.tsx    # mock
      AgentsView.tsx      # 실 CRUD (백엔드 + jsonb)
      BlocksView.tsx      # mock
      SessionsView.tsx    # mock
      ApprovalsView.tsx   # mock
  playground/
      Chat.tsx            # 005 채팅(Bubble/Sender) 이동 + 인스펙터(디버깅)
  api.ts                  # listAgents/createAgent/deleteAgent/streamChat (확장)
```

- 백엔드: 기존 `GET/POST/DELETE /agents`, `POST /agents/{id}/chat` 그대로. Agents 폼의 추가 필드는 `params`에 저장.

---

## 4. 진행 (실제) — 한 루프에 전 뷰 일괄 이식

당초 1~4 단계 분할로 계획했으나, 사용자가 1단계(셸) 확인 후 **"각 메뉴 상세 기능을 mock 포함 모두 옮겨달라"** 고 결정 → 단계 분할 대신 전 뷰를 일괄 이식했다.

1. **Shell & 테마** ✅ — `ConfigProvider` + `theme.css`(전체 토큰 팔레트) + `AdminShell`(navy 사이더/헤더/상태 뷰 전환) + `shared.tsx`(Page/StatusPill/Panel/DataTable/Drawer/Desc/VersionHistory/ExposeSwitch/DemoBanner) + `icons.tsx`(아이콘 레지스트리).
2. **기반 데이터** ✅ — `mockData.ts`로 `adminData.js` 전체(BLOCKS·ADMIN_AGENTS·SESSIONS·APPROVALS·상태맵 + 후처리) 타입 포함 이식.
3. **5개 뷰** ✅ — Overview / Agents(mock CRUD·버저닝·공개 토글) / Blocks(탭·드로어·MCP 등록 모달) / Sessions(필터·드로어) / Approvals(승인/거부). 병렬 서브에이전트로 이식.
4. **Playground** ✅ — agent-debug 3분할(피커·디버그 채팅·인스펙터) + 가짜 스트리밍 + HIL 승인 카드 + A2UI 생성형 UI + LangGraph 경로 인스펙터.

> 실 백엔드 연결(Agents CRUD→`params` jsonb, Playground→실 스트림, 세션·승인·메모리·MCP·A2A 실데이터)은 **이후 루프**에서 점진적으로.

---

## 5. 디자인 참조 보존
- handoff 번들을 `.dev/design-refs/`에 보관(작업 입력). 구현 시 `ui_kits/*`·`tokens/*`·`styles.css`·각 `*.prompt.md`를 명세로 참조.
- 번들의 `_ds_bundle.js`·아이콘 SVG는 우리 antd 6/`@ant-design/icons`로 대체하므로 코드에 포함하지 않음.

---

## 6. 검증 (결과)
- [x] `tsc --noEmit` exit 0, `vite build` ✓ 성공.
- [x] AdminShell 사이더(navy #001529)/헤더/상태 뷰 전환, 토큰 테마 적용.
- [x] 5개 뷰 + Playground 렌더 (mock 데이터).
- [x] 타자 비판 검증(codex review) — **GATE PASS (P1 0건)**, P2 5건 중 2건 수정.

### codex P2 처리
- ✅ 수정: Playground 언마운트 시 스트리밍 interval 정리(setState-after-unmount 방지).
- ✅ 수정: AgentsView revert 가드 — 승격할 archived 버전이 없는 유일 active 버전은 되돌리기 차단.
- 📝 mock 한계로 기록(이후 보완):
  - 신규 에이전트 생성 시 유일 버전이 draft인데 activeVersion=v1로 "서빙 중" 표시 (번들 동작 그대로).
  - 사이더 승인 배지가 static `PENDING_APPROVALS` — ApprovalsView 로컬 큐 처리 후 갱신 안 됨(상태 미공유).
  - `A2UISurface` 폼 상태가 새 surface 수신 시 재동기화 안 됨(현재 surface 1종이라 영향 미미).

---

## 6b. 디자인 개정 (handoff2 — 에이전트 출처)

claude.ai/design 번들이 개정됨(`Ant Design System-handoff2.zip`). 변경은 **Agents 뷰 + 데이터에 한정**(agent-debug·토큰·다른 뷰 동일).

- **출처(source) 개념 추가**: `ui`(콘솔에서 블록 조합 — 편집 가능) vs `code`(SDK로 정의·코드베이스 배포 — 엔드포인트+토큰으로 등록, **콘솔에선 읽기 전용**).
- mockData: 기존 4개에 `source:'ui'`, 코드 에이전트 `Doc Translator` 추가, `AGENT_SOURCE` 맵.
- AgentsView: **코드 에이전트 등록 모달**(엔드포인트+토큰→연결 테스트→Agent Card 수신→등록), **CodeAgentDetail**(읽기전용 + 배포/연결 박스 + 배포 히스토리 + 재동기화), 소스 컬럼, 코드 에이전트 편집 잠금/등록 해제.
- 검증: tsc 0, build ✓, **codex GATE PASS** — P2 2건 중 1건 수정(등록 모달 stale in-flight 테스트 가드), 1건 기록(translator `sessions:1`인데 대응 세션 행 없음 — handoff2 데이터 그대로, mock 한계).

## 7. 미해결 / 추후
- 실제 백엔드로 채울 항목: 모델 레지스트리, 메모리(Mem0), MCP(소비/노출), A2A, 권한·승인, 세션, 버저닝.
- URL 라우팅(딥링크 필요 시), 인증.
- 디자인 토큰을 antd `ConfigProvider` 토큰으로 완전 일원화할지(현재는 CSS 변수 병용).

## 관련 기록
- 디자인 명세: claude.ai/design handoff (`.dev/design-refs/`)
- 조사 출처: Claude Design 문서, antd v6 마이그레이션, antd 디자인 토큰·Figma 킷 (웹 확인 2026-06-19~21)
