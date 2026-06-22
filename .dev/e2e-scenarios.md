# E2E 테스트 시나리오 (007 실 에이전트 서비스)

도구: Playwright (`tests/e2e`). 전제: API(8000) + Postgres + 로컬 MLX(8045) + Vite(5173) 가동.
두 프로젝트: `api`(request 픽스처, 브라우저 없음) → `admin`(Chromium UI).

## A. API 통합 (`specs/api.spec.ts`)
1. **블록 집계** `GET /blocks` — 5 카테고리(persona/memory/embedding/permission/mcp), 각 items>0.
2. **블록 CRUD** — persona 생성→목록 확인→삭제. MCP 생성→publish 토글→삭제.
3. **에이전트 CRUD** — 생성(unique)→목록 포함→조회→삭제(404 확인).
4. **버저닝 상태머신**
   - 생성 시 v1 draft, activeVersion null.
   - 편집→draft 갱신(중복 안 생김). fork→이미 draft면 400.
   - activate(v1)→online, activeVersion=v1. active 재activate→400.
   - (시드 reviewer) archived 활성화=롤백 200, 유일 active revert→400.
5. **expose** — a2a 토글 true/false 반영.
6. **코드 에이전트 등록** — source=code, 토큰 마스킹, activeVersion=commit.
7. **세션/승인** — `GET /sessions` 시드 존재, 승인 resolve→상태 변경.
8. **채팅 런타임 + mem0**
   - 메모리 켠 에이전트로 사실 저장 → 새 대화에서 trace.memories 회상(>0).
   - 응답 토큰 스트리밍, `event: trace`(graph/tokens), 세션·메시지 영속(`/sessions/{id}/messages`에 assistant + trace).

## B. 브라우저 UI (`specs/admin.spec.ts`) — 실 백엔드 연결
1. **로드/네비** — 사이더 메뉴로 6뷰 전환, 헤더 제목 변경.
2. **개요** — 통계 타일 4개, 에이전트 카운트가 API와 일치.
3. **에이전트** — 목록에 시드 이름 표시. 새 에이전트 생성(고유명)→목록 등장→상세 드로어→삭제→사라짐.
4. **에이전트 공개 토글** — 스위치 on/off 반영(낙관/리프레시).
5. **빌딩 블록** — 탭 전환(권한/MCP 등), MCP publish 토글.
6. **세션** — 목록 렌더, 행 클릭→상세 드로어.
7. **승인** — 카드 거부/승인→큐에서 제거.

## 정리 원칙
- 각 테스트는 **고유 이름**(타임스탬프)으로 데이터를 만들고 끝나면 삭제 → 시드 오염 최소화.
- 읽기 단언은 시드 존재(에이전트 4+1, 블록 카테고리)에 의존. 사용자가 DB를 리셋하면 시드 재적재됨.
