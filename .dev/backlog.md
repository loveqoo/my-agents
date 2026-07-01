# Backlog — 작업 후보 보드 (AI 영역)

> Scaffolding의 **진입 재료**. "다음 뭐 하지?"에서 이 파일을 먼저 읽어 후보/완료/보류를 한눈에 본다
> (대화 재유도 대신 스캔). 굵은 단위(후보 작업)만 — 서브태스크는 안 쪼갠다(파편화 방지). learning/
> retrospect/spec의 `INDEX.md`가 회고 상기를 싸게 만들듯, 이 파일은 *백로그 상기*를 싸게 만든다.
> 규칙이 아니라 종이 한 장 — 새 작업 정해지면 여기서 옮기고, 끝나면 완료로 내린다.

## 후보 (다음에 할 만한 것)

- (없음 — 다음은 Scaffolding서 새 방향 모색)

## 진행 중

- (없음)

## 보류 / 후속 후보

- **admin UI에서 impl 선택 노출** — 생성된 flow(스펙 099 `route`·`orchestrate` 등)를 SPA 편집 폼
  드롭다운에서 고르게. 현재 편집 폼은 `impl`을 안 보냄(085 H5 갭). 스펙 099 §5 비목표로 남긴 후속.
- **능력 브로커 Phase 2 — kind 확장(MCP/RAG/memory) + 인가 입도 강화** — Phase 1(스펙 100)은
  kind=agent만·`(에이전트별 allowlist) ∩ (kind-단위 RBAC)`. 후속: (a) MCP/RAG/memory provider 추가,
  (b) per-cap·per-user 인가 + 에이전트 소유권(현재 Agent는 owner 없는 공유 카탈로그 → member에 kind
  RBAC 주면 접근 가능한 에이전트 allowlist 전부 호출 가능; codex 100 [P1] #1/#2 수용·명시경계),
  (c) 카탈로그 커지면 벡터/하이브리드 검색(설계결정 10), (d) admin UI capabilities allowlist 편집.
- **admin UI에서 capabilities allowlist 편집** — 에이전트 config `capabilities`를 SPA서 편집(현재
  DB 직접). Phase 2 (d)와 묶어도 됨.

## 완료 (요약 — 상세는 각 스펙/회고)

- **로드맵 12항목**(스펙 033, 034~042) — 2026-06-27 소진.
- **제안 8항목** — #1 conformance(089)·#2 입력히스토리(091)·#3 도구원본숨김(092)·#5 MCP/RAG삭제
  차단(093)·#6 오버플로(095)·#7 메모리검색UI일관(097)·#8 세션검색(098).
- **#4 트리노드 그래프빌더** — 폐기 후 스펙 099(agent-flow 스킬 코드젠, 데모 `route`)로 대체 해결
  (2026-07-01, 회고 080·learning 099).
- **능력 브로커 Phase 1**(스펙 100) — discovery 시임(discover/describe/invoke)+정책 게이트(allowlist∩
  RBAC deny-by-default)+A2A provider+데모 `orchestrate`(서브스텝 조립) 완료(2026-07-01, 회고 081·
  learning 100). codex 3런: #3(untrusted 데이터 채널 격리) 수정, #1/#2(인가 입도) 명시경계로 문서화.
