# 004 — Admin Web UI(채팅) 루프 회고

날짜: 2026-06-19
지배 스펙: [docs/spec/003-admin-web-ui-chat.md](../../docs/spec/003-admin-web-ui-chat.md)

## 루프 개요
- **목표:** 등록된 에이전트와 브라우저에서 스트리밍 채팅하는 테스트용 web UI(React+TS+Antd, Vite).
- **계기:** 부가 기능보다 "내가 직접 테스트할 환경"을 먼저. (채팅만, 등록은 API로)
- **단계 흐름:**
  - 1 Scaffolding — `admin/`(Vite) 신규, API에 CORS
  - 2 Context — 결정 질문(스택=React/TS/Antd, 범위=채팅만, 서빙=Vite 별도 포트)
  - 3 Planning — `docs/spec/003`(AI 초안 → 인간 검토 → 승인)
  - 4 Execution — admin 앱(에이전트 선택 + SSE 채팅), CORS, fetch+ReadableStream SSE 파싱
  - 5 Verification — 빌드·서빙·CORS·SSE 확인 + codex 리뷰(P2 8) → 6건 수정
  - 6 Compounding — 본 회고 + 학습 007

## 무엇이 잘못됐나 / 배운 것
- **포트 점유로 수정 미반영:** API 재기동 실패(address already in use)로 옛 코드가 응답. → [[007]]
- **CORS 오리진 누락:** `localhost`만 허용 → `127.0.0.1:5173` 접속 시 실패. 둘 다 허용.
- **SSE 파서 견고성(codex):** 남은 버퍼 flush, `text` 문자열 검증 추가. (`\r\n`/다중 data는 follow-up)
- **React 함정(codex):** StrictMode 이중 fetch 가드, 스트림 abort(전환 시), 중복 전송 ref 가드.

## 잘된 것
- **타자 검증(codex)**이 React/SSE 함정(abort·StrictMode·파서)을 다수 포착 — 자가검증으론 놓쳤을 것.
- **사용자가 실제로 즐겁게 사용** — 페르소나 바꿔가며 시 놀이. 끝-끝 가치 확인.
- "간단하게" 기조 유지: 채팅만, 의존성 최소, 빌드 1초.

## 다음에 다르게 할 것
- 백그라운드 서버는 종료 후 **포트 확인→재기동→변경점 검증** 루틴. → [[007]]
- UI는 빌드/서빙뿐 아니라 가능하면 **헤드리스 브라우저 렌더 검증**도 고려.

## 관련 기록
- [[007]] 백그라운드 서버 재기동 시 포트 정리
- 이전 회고: [003-persona-registry-and-chat](./003-persona-registry-and-chat.md)
