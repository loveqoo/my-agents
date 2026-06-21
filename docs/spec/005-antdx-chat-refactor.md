# 005 — Ant Design X로 채팅 UI 리팩터

상태: **승인됨 (실행)**
날짜: 2026-06-21
대체 대상: [003-admin-web-ui-chat.md](./003-admin-web-ui-chat.md), [004-web-ui-prompt-inspect.md](./004-web-ui-prompt-inspect.md)

> 손으로 만든 채팅/디버깅 UI를 **Ant Design X**(`@ant-design/x`) 공식 AI 채팅 컴포넌트로 교체.
> 앞으로 기능을 계속 붙일 수 있는, 잘 다듬어진 UI/UX 토대를 마련한다.

---

## 1. 목표 / 비범위

### 목표
- 채팅 영역을 **Bubble.List + Sender**로 교체(스트리밍·자동 스크롤 내장).
- 디버깅 영역(프롬프트 확인)은 **ThoughtChain**으로 표현(읽기 전용 유지).
- 2단 레이아웃 `|채팅|디버깅|`과 기존 동작(에이전트 선택, SSE, 멀티턴, 프롬프트 확인) 보존.

### 비범위
- 백엔드 변경 없음(기존 `GET /agents`, `POST /agents/{id}/chat` SSE 그대로).
- 새 기능(첨부·세션목록·툴 호출 시각화 등)은 토대만 두고 추후.

---

## 2. 결정 요약 (초안)
| 항목 | 결정 |
|---|---|
| 라이브러리 | `@ant-design/x` v2.8 |
| antd | **5 → 6 업그레이드** (peer `antd ^6.1.1`) + `@ant-design/icons` 6 |
| React | 18 유지 (x/antd6 peer `react >=18`) |
| 채팅 | `Bubble.List`(메시지) + `Sender`(입력) |
| 스트리밍 | 기존 `streamChat`(fetch+reader) 유지하고 Bubble에 연결 (가장 단순). XStream 도입은 추후 검토 |
| 디버깅 | `ThoughtChain` — system(페르소나)/대화 메시지를 항목으로 |
| 상태 | 무상태 서버 유지 — 브라우저가 messages 보관 |

> 스트리밍: Ant Design X의 `useXChat`/`XRequest`로 갈아탈 수도 있으나, 우리 SSE 포맷(`data:{"text"}`)이 단순하므로
> 1차 리팩터는 **기존 streamChat 재사용**으로 위험을 줄인다. (useXChat 전환은 §6 추후)

---

## 3. 변경 범위 (프론트)
```
admin/
  package.json        # +@ant-design/x, antd ^6, @ant-design/icons ^6
  src/
    App.tsx           # antd 6 점검(Select/Layout/Spin/message) — 대부분 호환
    components/
      Chat.tsx        # Bubble.List + Sender + ThoughtChain 로 재작성
    api.ts            # 변경 없음(streamChat 재사용)
```
- antd 6 breaking: 대부분 API 호환. `Button.Group`→`Space.Compact`(이미 사용 중). 아이콘 패키지 동반 업그레이드 필요.

---

## 4. 핵심 흐름 (동작 보존)
1. `GET /agents` → 선택(드롭다운 유지).
2. **시스템 프롬프트(페르소나)는 선택 드롭다운 바로 아래에 상시 표시.**
3. 입력(Sender) → 로컬 messages push → `streamChat` 호출.
4. SSE 토큰 → 진행 중 assistant **Bubble**에 실시간 append(typing 효과).
5. **디버깅은 온디맨드:** 각 assistant 응답의 "프롬프트 보기" 링크를 누르면,
   그 응답을 생성할 때 보낸 전송 페이로드(`[system: 페르소나] + 그 응답 직전까지의 대화`)만
   디버깅 영역에 표시. (전부 나열하지 않음)

### UI 수정 사항 (피드백 반영 2026-06-21)
- 입력 영역(Sender)이 그레이라 disabled처럼 보이는 문제 → Layout/입력 영역 배경 흰색·테두리 명확화.
- 디버깅 영역과 채팅 영역의 행 싱크가 안 맞는 문제 → 전부 나열 대신 위 "온디맨드" 방식으로 전환.
- 좌우 컬럼은 동일 고정 높이(72vh) + 독립 스크롤.

---

## 5. 검증 (완료 기준)
- [ ] `npm install` 후 antd 6 + x v2.8 의존성 충돌 없이 설치.
- [ ] `npm run build` 통과.
- [ ] 에이전트 선택 → Sender로 전송 → Bubble에 **스트리밍 표시**.
- [ ] 멀티턴 맥락 유지.
- [ ] 디버깅 영역에 페르소나 + 전송 메시지 표시(읽기 전용).
- [ ] 타자 비판 검증(codex) 통과.

---

## 6. 미해결 / 추후
- `useXChat` + `XRequest`/`XStream`으로 스트리밍 관리 일원화.
- ThoughtChain으로 **실제 툴 호출**(MCP 도입 시) 시각화.
- Conversations(세션 목록), Attachments, Prompts/Suggestion 등 X 컴포넌트 점진 도입.
- antd 6 전환 중 발견되는 개별 컴포넌트 조정 사항.

## 관련 기록
- 대체: [003](./003-admin-web-ui-chat.md), [004](./004-web-ui-prompt-inspect.md)
- 조사 출처: Ant Design X 공식 문서, antd v5→v6 마이그레이션 가이드 (웹 확인 2026-06-21)
