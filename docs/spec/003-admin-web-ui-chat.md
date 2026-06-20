# 003 — Admin Web UI: 채팅 (테스트 환경)

상태: **승인됨 (실행)**
날짜: 2026-06-19
지배 스펙: [001-system-overview.md](./001-system-overview.md) (Admin SPA)
연동 대상: [002-persona-registry-and-chat.md](./002-persona-registry-and-chat.md) (REST + chat SSE)

> 등록된 에이전트와 **브라우저에서 스트리밍 채팅**할 수 있는 web UI. 직접 손으로 테스트할 환경이 목적.

---

## 1. 목표 / 비범위

### 목표
- React+TS+Antd(Vite) SPA에서 **에이전트를 골라 대화**한다.
- chat은 API의 SSE를 받아 **토큰을 실시간 표시**한다.

### 비범위 (이 증분 제외)
- 에이전트 **등록/수정/삭제 UI** (등록은 API로 — "채팅만")
- 인증, 배포 빌드/정적 서빙, 모델·MCP·메모리 관련 화면
- 서버측 대화 상태 (히스토리는 **브라우저가 보관**)

---

## 2. 결정 요약 (초안)

| 항목 | 결정 |
|---|---|
| 스택 | React + TypeScript + Antd, **Vite** |
| 위치 | `admin/` (워크스페이스 밖, 별도 빌드) |
| 서빙 | Vite 개발 서버(별도 포트, 예: 5173) |
| API 연동 | `GET /agents`(선택용), `POST /agents/{id}/chat`(SSE) |
| CORS | FastAPI에 CORSMiddleware로 `http://localhost:5173` 허용 |
| 대화 상태 | 무상태 서버 — 브라우저가 messages 보관·전달 |
| SSE 수신 | `fetch` + ReadableStream 리더로 `data:` 프레임 파싱 (POST라 EventSource 불가) |

---

## 3. 구조

```
my-agents/
  admin/                        # 신규 (Vite React-TS)
    package.json
    tsconfig.json
    vite.config.ts
    index.html
    .env.example                # VITE_API_BASE=http://localhost:8000
    src/
      main.tsx
      App.tsx                   # 에이전트 선택 + 채팅 레이아웃
      api.ts                    # listAgents(), streamChat()
      components/
        Chat.tsx                # 메시지 목록 + 입력 + SSE 스트리밍
```

- API 측 변경: `packages/api/src/api/main.py`에 **CORSMiddleware** 추가.

---

## 4. API 연동 계약 (기존 002 재사용)
- `GET /agents` → 선택 드롭다운/리스트 채우기.
- `POST /agents/{id}/chat` body `{messages:[{role,content}]}` → `text/event-stream`.
  - 프레임: `data: {"text": "..."}` 누적, 종료는 `event: done` / `data: [DONE]`.
  - 브라우저는 `fetch`로 호출해 `response.body` 리더로 청크를 읽고 `\n\n` 단위 파싱.

---

## 5. 핵심 흐름
1. 앱 로드 → `GET /agents`로 목록 → 사용자가 에이전트 선택.
2. 입력창에 메시지 → 로컬 `messages`에 push → `POST /chat` 호출.
3. SSE 토큰을 받아 **진행 중 assistant 메시지에 실시간 append**.
4. `[DONE]` 수신 시 메시지 확정, 히스토리에 보관(다음 턴에 함께 전송).

---

## 6. 환경 / 설정
- `admin/.env`: `VITE_API_BASE=http://localhost:8000`
- 실행: API(`uv run api`) + Postgres + `npm run dev`(admin) 동시 기동. 전제: Node/npm(있음).

---

## 7. 검증 (완료 기준)
- [ ] `npm run dev`로 admin 기동, 브라우저 접속.
- [ ] 에이전트 목록이 보이고 선택 가능.
- [ ] 메시지 전송 → **토큰이 실시간 스트리밍**되어 표시.
- [ ] 멀티턴: 이전 맥락이 유지됨(브라우저 히스토리 전송).
- [ ] 타자 비판 검증(codex) 통과.

---

## 8. 미해결 / 추후
- 등록/삭제 UI, 모델/파라미터 편집
- 에러 표시(에이전트 없음/네트워크), 로딩 상태 정교화
- 배포 빌드 + FastAPI 정적 서빙(단일 출처)로 전환
- 인증
- SSE 파서: `\r\n\r\n` 프레임/이벤트당 다중 `data:` 라인 대응(현재는 자체 서버 포맷만 가정)
- build에 `tsc --noEmit` 타입체크 추가(현재 dev 편의로 생략)

## 관련 기록
- [001 §Admin SPA](./001-system-overview.md), [002 chat SSE](./002-persona-registry-and-chat.md)
