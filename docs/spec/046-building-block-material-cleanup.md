# 046 — 빌딩블록 재료 정리: 코드·인프라 권한/MCP 제거 + 데모 에이전트 삭제

> 마스터 044 배치 2. UI 테스트 #4(권한: 웹 에이전트에 파일/터미널/repo/k8s 권한 불필요)·
> #5(미구현 MCP 정리). 테마: **순수 웹 에이전트 플랫폼에 맞게 카탈로그를 비운다.**
> 관련: 044(결정·트리아지), learning 025(시드↔레지스트리 drift는 소스만 고치면 안 됨—라이브 DB도),
> learning 042(참조는 양방향—제거 권한을 쓰는 에이전트 config도), learning 043(코드층·데이터층 분리),
> learning 037(파괴적 작업 경계), memory adversarial-review-before-destructive-ship.

## 배경·결정

044에서 #4는 "코드·인프라 권한 전부 제거"로 결정됨. 046 착수 중 권한 제거가 MCP·에이전트·HIL
데모로 연쇄됨을 발견 → 사용자에게 2건 추가 질문(2026-06-28, AskUserQuestion):

| 주제 | 결정 |
|---|---|
| #5 MCP 정리 범위 | **코드/인프라 MCP만** 제거(filesystem·github·prometheus·kubernetes), 웹용 유지 |
| 권한 잃는 데모 에이전트(Code Reviewer·Ops Copilot) | **에이전트째 제거** |

## 제거/유지 명세 (측정 가능)

**권한**(permissions 테이블 + seed.PERMISSIONS):
- 제거(5): `files.read`, `repo.read`, `repo.merge`, `k8s.read`, `k8s.write`
- 유지(3): `web.search`, `calendar.rw`, `mail.send`

**MCP**(mcp_servers 테이블 + seed.MCP_SERVERS):
- 제거(4): `filesystem`, `github`, `prometheus`, `kubernetes`
- 유지(6): `tavily`, `gcal`, `gmail`, `notion`, `acme-weather`, `partner-crm`

**에이전트**(agents 테이블 + seed.AGENTS):
- 제거(2): `agt_rvw_2b91c4`(Code Reviewer), `agt_ops_5c0833`(Ops Copilot)
- 유지(2): `agt_rsch_7f3a91`(Research Assistant), `agt_sec_9d4417`(Personal Secretary)

**유지 에이전트의 dangling 참조 정리**(learning 042 — soft JSON 참조라 FK가 안 잡아줌):
- Research Assistant config + 모든 version.config: `permissions`에서 `files.read` 제거(→`["web.search"]`),
  `mcps`에서 `filesystem` 제거(→`["tavily"]`).
- Personal Secretary: 제거 대상 미참조 → 무변경.

## 연쇄·FK 처리 (참조 무결성)

에이전트 삭제 시(models.py FK):
- `agent_versions.agent_pk` → **CASCADE**(버전 자동 삭제).
- `sessions.agent_pk` → **CASCADE**(세션 + messages 자동 삭제). 삭제 에이전트의 세션(예 sess-6c93
  Code Reviewer)도 함께 사라짐 — 의도된 정리.
- `approvals.agent_pk` → **SET NULL**(승인 행은 남고 agent_pk만 NULL). 시드 데모 승인
  apr-3391(repo.merge)·apr-3388(k8s.write)는 삭제 에이전트 + 제거 권한을 참조 → seed.APPROVALS에서
  제거(재시드 방지). 라이브 DB의 잔존 승인 행 정리는 050(파괴적 데이터)로 유예하되, 본 작업의
  dry-run이 현황을 보고.

## 비범위 (중요)

- **`runtime.py`는 건드리지 않는다.** `_APPROVAL_ACTIONS`(github.merge_pr→repo.merge,
  kubernetes.scale→k8s.write)·`_CANNED`는 빌딩블록 *카탈로그*가 아니라 런타임 *정책/합성툴* 코드다.
  `tests/verify_041_hil_approval_gating.py`가 이 dict 내용에 정확히 의존(G6). 카탈로그에서 github/
  kubernetes MCP를 빼면 어떤 에이전트도 그 툴을 wiring하지 않아 **게이트는 살아있되 트리거만 없는**
  상태 = 사용자 의도("HIL 메커니즘 041 보존, 데모 트리거 소멸")와 정확히 일치. 041 테스트 green 유지.
- MCP 실구현(langchain-mcp-adapters)은 본 라운드 밖(044). 카탈로그 행 정리만.
- 라이브 DB의 비-시드 잔존 데이터(테스트로 생긴 세션·승인)의 전수 정리는 050.

## 실행 계획

1. **seed.py**(코드층): `PERMISSIONS` 3개로, `MCP_SERVERS` 6개로, `AGENTS` 2개로(+Research의
   files.read·filesystem 참조 제거), `APPROVALS` 빈 리스트로. 재시드가 제거분을 재생성하지 않게.
2. **admin**: `AgentsView.tsx:412` 신규 에이전트 기본 permissions `['web.search','files.read']`
   →`['web.search']`. mockData의 죽은 `BLOCKS`/관련 잔재가 있으면 정리(BlocksView는 백엔드 API에서
   카탈로그를 읽음 — 표시 출처는 DB).
3. **라이브 DB 정리**(데이터층, learning 025): dry-run 스크립트
   `tests/cleanup_046_blocks.py`가 (a) 삭제/수정 대상을 **읽기 전용으로 리포트**, (b) `--apply`
   플래그가 있을 때만 트랜잭션으로 실행(권한 5행·MCP 4행 delete, 에이전트 2행 delete[cascade],
   유지 에이전트 config·version.config의 dangling 이름 strip). 사용자 검토 후 apply.

## 검증(자가 + 타자)

1. **dry-run 리포트**: 삭제 대상 수·이름이 명세와 일치(권한 5/MCP 4/에이전트 2), 유지분 보존 확인.
2. **참조 무결성 단위** `tests/verify_046_integrity.py`: apply 후 (a) 제거 권한/MCP 이름이 어떤
   agents/agent_versions config에도 안 남음(dangling 0), (b) 제거 권한·MCP·에이전트 행 부재,
   (c) 유지 권한 3·MCP 6·에이전트 2 존재, (d) 시드 재호출이 제거분을 되살리지 않음(seed_if_empty 멱등).
3. **041 회귀**: `tests/verify_041_hil_approval_gating.py` 여전히 green(runtime 미변경 확인).
4. **프론트 빌드**: admin `tsc` 통과.
5. **타자(적대 서브에이전트 리뷰)**: "제거가 남긴 dangling 참조? cascade가 의도 밖 데이터를 지우나?
   유지 에이전트가 깨지나? seed/DB drift? 041·chat 경로가 제거 MCP를 가정하나? 비밀 누출?"
6. **브라우저**(Playwright+시스템 Chrome): BlocksView 권한 탭 3행·MCP 탭 6행, AgentsView 2 에이전트
   시각 확인.

## 검증 결과

**적용**: `cleanup_046_blocks.py --apply` 트랜잭션 커밋 완료(권한 5행·MCP 4행 delete,
에이전트 2행 delete[cascade], 유지 에이전트 dangling strip). dry-run이 라이브 DB에 시드 외
16 세션·8 승인(모두 resolved, pending 0)이 있음을 드러냄 — 045 배지 불변 확인.

1. **참조 무결성 단위** `tests/verify_046_integrity.py` — **I1~I6 전부 PASS**:
   제거 권한/MCP/에이전트 행 부재(I1·I2·I3), 유지분 보존, dangling 0(I4: config + version.config),
   pending 승인 0(I5), seed_if_empty 멱등(I6).
2. **041 회귀** `tests/verify_041_hil_approval_gating.py` — **GREEN**(runtime `_APPROVAL_ACTIONS`
   미변경). probe_041 통합 프로브는 트리거 빌딩블록 소멸로 graceful **SKIP**(크래시 아님) 확인.
3. **프론트 빌드** `tsc` — 통과(AgentsView 신규 코드-에이전트 기본 permissions `['web.search']`).
4. **적대 서브에이전트 리뷰** — B1(stale 픽스처: shot-agents-037이 삭제된 Code Reviewer 클릭)·
   B2(probe_041 scalar_one 크래시 + 통합 rung 상실)·B3(verify 부재)·W1(리포트가 pending 미경고)
   네 건 발견 → 전부 수정(§7 빚 반영).
5. **브라우저**(Playwright+시스템 Chrome) `tests/browser/shot-blocks-046.mjs` — **22/22 단언 통과**:
   BlocksView 권한 탭 3행·MCP 탭 6행(코드/인프라 재료 부재), AgentsView에 Code Reviewer/Ops Copilot
   부재·Research/Personal Secretary 존재. Research의 MCP가 `tavily`만 표시(filesystem strip 시각 확인).
   스샷: `/tmp/blocks046-{1-permissions,2-mcp,3-agents}.png`.

## §7 빚·한계

- 라이브 DB의 비-시드 잔존(테스트 세션·승인)은 050에서 전수 정리 — 046은 시드 정의분 + 명세된
  제거만.
- runtime `_APPROVAL_ACTIONS`는 카탈로그에 없는 (github,kubernetes) 키를 유지 — 의도된 정책 보존
  (게이트는 미래 웹 액션 추가 시 재사용 가능). 041 그대로.
- **HIL 라이브-DB 통합 rung 상실(적대 리뷰 B2)**: `.dev/probe_041_chat_integration.py`는 github
  MCP + agt_rvw_2b91c4를 태워 chat.py 글루를 증명했으나, 046이 그 트리거 빌딩블록을 *설계상*
  제거하므로 해당 통합 시나리오는 더 이상 시드되지 않는다. 프로브는 크래시 대신 SKIP하도록 고쳤다.
  게이트 *메커니즘*은 runtime 정책으로 보존, 단위 *시맨틱*은 `tests/verify_041`이 green으로 유지.
  미래에 admin 승인이 필요한 웹 액션이 추가되면 그 빌딩블록으로 통합 rung을 재구성한다
  (self-fixture가 바람직 — 시드 데모 데이터에 결합하지 않게). 관련: verification-ladder-three-rungs.
- SET NULL 후 8개 고아 승인(repo.merge/k8s.write, 모두 resolved)은 카탈로그에 없는 권한명을 보존 —
  pending 0이라 045 배지 불변. 라이브 데이터 전수 정리는 050. cleanup 리포트가 pending 승인을
  ⚠로 명시 경고(미래 pending이 배지에 새지 않도록).
- 삭제 16 세션의 langgraph 체크포인트 행(thread_id 키, FK 없음)은 고아로 남음 — 기능 무해(재개는
  agent_pk=NULL 가드로 스킵), 스토리지 빚으로 050 후보. 적대 리뷰 C4 확인.
- 에이전트 삭제는 비가역 — dry-run 검토 + 트랜잭션 + 백업 권고로 완화.
