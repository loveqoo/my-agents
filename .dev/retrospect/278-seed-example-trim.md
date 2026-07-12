# 278 — 첫 설치 시드 예제 트림(스펙 303)

## 무엇을 했나
"처음 설치 후 보이는 예제가 정돈되지 않았다"(사용자)를 두 층으로 분리 — **테스트 잔해**(dev DB 58
에이전트 중 53개=verifier/브라우저 산물, 신선 설치엔 없음, OUT)와 **시드 예제**(`seed_if_empty`가 심는
진짜 첫 설치 데이터, IN). 후자에서 고아·빈 데모를 걷어냄: 페르소나 4→2(strict-senior-engineer·calm-sre
제거)·컬렉션 4→3(support-tickets 제거)·세션 4→0(빈 껍데기 전부 제거)·시드 도크 "mockData 미러" 주석 정정.

## 배운 것 / 복리 포인트

- **"정돈 안 됨"은 먼저 층을 갈라야 스코프가 선다**. 첫인상은 "예제가 지저분"이지만 실제론 두 출처가
  섞여 있었다 — 신선 설치에 실제로 심기는 seed(트림 대상)와, dev DB에만 쌓인 테스트 산물(53개, seed
  아님·teardown 문제). 사용자가 본 화면 = seed ∪ test-debris. **어느 층이 사용자를 괴롭히는지 확정하기
  전에 손대면 엉뚱한 걸 지운다** — 사용자와 "신선 설치 기준"으로 스코프를 합의(seed만)하고 test-debris는
  별개 backlog로. → [[census-lens-not-a-fact]] 계열(무엇을 세느냐가 답을 정한다).

- **고아 판정은 "실 참조"로, 주석·산출물 언급은 참조 아님**. strict-senior-engineer·calm-sre는 스펙 046서
  Code Reviewer/Ops Copilot이 제거되며 참조가 끊긴 고아였는데, 전역 grep에 유일하게 걸린 건
  `tests/browser/out-scenario/scorecard.json`의 calm-sre — 이건 과거 브라우저 런의 **출력 산출물**(생성된
  결과)이지 시드를 소비하는 픽스처가 아니다. **"어딘가 이름이 나온다"≠"참조된다"** — 산출물/주석 언급과
  실 배선(에이전트 config.persona / vectorTables)을 구분해야 진짜 고아를 안전히 제거한다. → [[move-breaks-references-both-directions]]

- **시드가 상수→행 1:1이면 단위 검증의 충실도가 라이브 시드에 근접**. `_seed_personas`는 `PERSONAS`를
  그대로 `add_all` — 상수와 심긴 행 사이에 변환이 없다. 게다가 이번 변경은 **행 제거만**이라 새 제약
  위반(NOT NULL·unique)을 만들 수 없다. 그래서 postgres가 내려가 rung 2(신선 빈 DB 시드 카운트)를 못
  돌리는 동안에도, 카탈로그 상수의 카운트·참조무결·고아0을 재는 단위 verifier가 "심길 값"을 사실상 그대로
  측정한다. **rung 대체 가능성은 변환 유무·변경 방향으로 판단** — 추가라면 라이브 제약 검증이 꼭
  필요하지만, 순수 제거+무변환 매핑이면 단위가 라이브를 대리한다. → [[verification-ladder-three-rungs]]

- **"인프라 없음"을 결론 내리기 전에 한 겹 더 — 내려간 게 데몬인지 컨테이너인지 분리**. 처음엔
  "postgres·docker·compose 로컬 부재"로 rung 2를 미실행 처리했는데, 사용자가 "docker로 떠 있다"고
  하자 다시 파고드니 실상은 (1) OrbStack VM 자체가 내려가 소켓 파일이 없었고(`orb start`로 기동),
  (2) 기동 후에도 뜬 건 **다른 프로젝트**(`absence-postgres`)였고 (3) 내 `my-agents-postgres-1`은
  7시간 전 Exited라 `docker start`로 따로 살려야 했다. "docker가 안 붙는다"는 한 신호에서 "인프라 없음"으로
  점프하면 3겹(VM·타 컨테이너·내 컨테이너)이 뭉뚱그려진다. **사용자 보고가 내 측정과 어긋나면 내 측정을
  의심하고 계층을 갈라라** — 덕분에 rung 2를 실제로 돌렸다(일회용 DB로 전체 alembic+seed 실측
  2/3/0/5/0, 라이브 `agents` 무접촉 확인). → [[probe-deeper-before-concluding]] [[user-is-remote-do-host-actions-yourself]]

- **RBAC/적대 rung은 스펙 성격으로 트리거 — 데이터 큐레이션엔 강제 안 됨**. 소유권 체크리스트는
  "유저별 데이터·소유권 컬럼·비가역 경로"를 만질 때 자동 적용이고, 시드 예제 트림은 그중 어디에도 안
  닿는다(전역 시드 상수·읽기 전용 카탈로그). codex 적대 rung을 안 태운 건 스킵이 아니라 **트리거 미해당**
  — "일반 기능 스펙엔 강제하지 않는다"의 정직한 적용. 규칙을 기계적으로 다 돌리는 게 아니라 신호로 켠다.

- **정직한 빈 상태 > 가짜 채움**. 세션 4개는 전부 turns=0·Message 행 없는 빈 껍데기였다(스펙 056서 이미
  카운터를 진실화해둠). "화면이 빈 상태가 아니라 의미있는 데이터로"라는 seed 원칙과 정면으로 어긋난다 —
  **빈 세션은 의미 데이터가 아니다**. 채널/상태 다양성 데모를 위해 남기느니, 첫 설치 세션 화면은 정직하게
  비우고 실사용으로 채워지게 하는 게 정예에 맞다(사용자도 "지워도 된다" 승인). → [[beauty-equals-trust]]

## 검증 (사다리)
- **단위(rung 1)**: `verify_303_seed_trim.py` 11/11 — 카운트(페르소나2·컬렉션3·세션0·승인0)·제거항목
  부재·참조무결(dangling0)·고아0. seed가 상수→행 1:1이라 충실도 높음.
- **게이트**: metrics-fast 0(ruff·format·xenon·MI·naming·mypy 106파일).
- **실인프라(rung 2)**: `smoke_303_fresh_seed.py` — 일회용 DB(`agents_seed_smoke_303`)에 **전체 alembic
  마이그레이션 체인 + `seed_if_empty`** 실행 후 실측 카운트 = 페르소나2·컬렉션3·세션0·에이전트5·승인0,
  고아 미적재. 라이브 `agents` DB 무접촉(persona=4·agents=58 불변으로 확인)·스모크 DB drop 완료.
  (OrbStack·`my-agents-postgres-1` 기동은 내가 직접 — 위 복리 포인트.)
- **rung 3(적대) 미해당**: 유저데이터·소유권·비가역 경로 아니라 RBAC/codex 트리거 불성립(스킵 아님).
- 화면 재시드(현 dev DB 초기화, 파괴적)는 여전히 사용자 명시 시에만.

## 남은 것 / 주의
- **seed는 빈 DB에만** 실행 → 현재 dev DB엔 미반영. 트림 결과를 화면으로 보려면 재시드(DB 초기화, 파괴적)
  필요 — 사용자 명시 시에만.
- backlog: 테스트 잔해 53 에이전트 정리(teardown 개선)·mockData.ts 死데이터 배열 제거(타입/상수 보존)는 별개.
