# 회고 218 — 진단용 기록(env)에도 세 가지 정확성 축이 있다 (스펙 240, AgentOps A)

## 무엇을 했나
AgentOps 루프 A: EvalRun에 agent_version+env(경량 환경 기록) 박제, UI 버전 칩·실행 환경 표시.
외부 제안의 "완전 재현 Snapshot"은 경량화(재현 보장 아닌 진단 단서 — 정직한 계약). codex가 기록
자체의 결함 3건을 적발(비밀 노출·오버라이드 거짓 params·ORM 파생 필드 착각) → 수정.

## 배운 것

### 1. "진단용이라 대충"은 없다 — 기록도 노출·정합·수집성공의 3축을 탄다
env는 부가 기록인데도: (a) params 원문 기록=비밀 노출 축(성적표 JSON 덤프로 api_key 노출 —
[[playground-is-precision-debug-channel]]의 캡+마스킹 원칙은 진단 표면에도), (b) 오버라이드 런에
name만 바꾸고 params는 기본 모델 것=거짓 기록 축(부분 갱신은 불일치를 만든다), (c) serializer 파생
필드(embedding_model_name)를 ORM 속성으로 착각=수집 실패 축(Out 스키마 필드≠ORM 컬럼 — 파생은
조인으로). 기록 기능도 기능이다.

### 2. NULL은 버그가 아니라 사실일 수 있다 — 단언은 "무엇과 일치"로
새 에이전트는 초안만 있어 활성 버전이 None → 런의 None은 정직한 기록인데, 테스트가 truthy를
요구해 FAIL. 단언을 "활성 버전과 일치"로 고치니 의미가 선명해짐(전환 추적은 별도 케이스가 증명).
[[complement-attack-can-be-honest-boundary]]의 테스트 판.

### 3. 외부 설계 제안은 "이미 있는 것"과 대조부터 — 절반은 기존 자산이었다
AgentOps 제안 7항목 중 수집·수확·평가·회귀비교·실측은 기존(209·137~143·138·205)이 커버.
INDEX/백로그 대조로 진짜 갭 4개(A~D)로 좁혀 로드맵화 — 제안을 통째로 구현했으면 중복 공사였다.
과설계 후보(완전 재현 Snapshot)는 목적(귀속·진단)으로 되물어 경량화.

## 다음에 적용
- 진단/기록 표면 추가 시: 마스킹(키 기반 재귀)·부분 갱신 불일치·ORM vs 파생 필드 3축 점검.
- 부재(None) 단언은 "기대값과 일치"로(truthy 강요 금지).
- 외부 제안 검토 = 기존 자산 대조표 먼저(갭만 남긴다).

관련: 스펙 240 · AgentOps 로드맵(.dev/backlog.md) · [[use-codex-for-adversarial-verification]]
