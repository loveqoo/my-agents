# 회고 213 — 비영속 "쓰기 0": 세션/메시지만 세면 숨은 쓰기 경로(체크포인터)를 놓친다 (스펙 235)

## 무엇을 했나
사용자 요구: "1회성 추론을 위해 기능 다 끄기 = DB에 적재 안 함"(고트래픽·기록 무의미). `config.ephemeral`
플래그 신설 → `_persist` 무동작·메모리 off. 실측 테스트(채팅 1턴 전후 Session/Message 행 0 증가)로 초록.
**믿지 않고** codex 적대 검증 → _persist 밖 3개 쓰기 경로 적발(HIL 체크포인터·approval·langfuse) → 봉합·
인과 재검증. 관리 UI엔 경계(모델 동작/저장·영속)를 폼 표준 SectionHeader로 나누고 토글 추가.

## 배운 것

### 1. "쓰기 0" 검증은 *내가 아는 테이블*이 아니라 *턴이 건드릴 수 있는 전부*를 세야 한다
Session/Message만 세고 초록을 냈지만, langgraph **체크포인터(AsyncPostgresSaver)**가 매 superstep에
`checkpoints/checkpoint_writes/blobs`에 쓴다(비-ephemeral 대조군 Δ=3). 내 테스트는 이 테이블을 안 세서
못 봤다 — codex가 "_persist 밖 쓰기 경로"(여집합)를 물어 팠다. **교훈: 부재(0)를 주장하는 테스트는 "무엇의
0인지"의 목록이 완전해야 한다. 도메인 지식으로 목록을 좁히면 그 밖이 사각.** [[cap-the-raw-source-not-the-buffer]]
(막은 척)·[[verification-ladder-three-rungs]].

### 2. 측정 대상을 실제로 *활성화*하지 않은 "0"은 봉합 증명이 아니라 하네스 공백
체크포인터 테이블을 세도, 인프로세스 테스트가 lifespan을 안 돌려 `get_checkpointer()`가 None → 대조군도
checkpoint를 안 써서 E6(ephemeral 0)이 **vacuous**(내 ckpt=None 봉합과 무관하게 0). 실 `init_checkpointer()`를
불러 대조군이 진짜 3행을 쓰게 만든 뒤에야 E6이 **인과 검증**("봉합 없으면 ephemeral도 3행 썼을 것")이 됐다.
**교훈: 대조군이 그 신호를 실제로 내지 못하면 "0"은 아무것도 증명 못 한다 — 인과 대조는 신호원을 켜야 성립.**
[[probe-deeper-before-concluding]]·회고 212(무배선 대조로 vacuous pass 봉합)의 같은 함정 재발.

### 3. 구조적 봉합 > 지점 봉합 — ckpt=None 하나가 3갭을 동시에 닫았다
approval 쓰기를 개별 게이트하는 대신 **체크포인터를 안 붙이면** interrupt가 성립 안 해 approval 경로가
*구조적으로* 미도달 + checkpoint 미기록. 한 원인(체크포인터 부재)이 두 증상(approval·checkpoint)을 함께
없앴다. **교훈: 여러 갭이 한 메커니즘에서 파생되면 그 메커니즘을 끊어라 — 증상마다 가드를 다는 것보다 견고.**

### 4. 새 config 필드는 "다배선 미러링"을 열거로 — persistHistory가 이미 경고를 남겨뒀다
`ephemeral`이 저장 안 돼 첫 테스트가 FAIL — Pydantic `model_dump`가 스키마에 없는 키를 조용히 드롭.
schemas.py의 persistHistory 옆 주석이 바로 이 함정("model_dump 드롭·seed-bypasses-write-schema")을 경고
중이었다. `grep persistHistory`로 8개 배선점(스키마×2·직렬화·타입·매핑×3·mock×2)을 열거해 미러링.
**교훈: 라운드트립되는 새 필드는 선례를 grep해 배선점을 닫힌 집합으로 센다(하나 빠지면 조용히 무효).**
[[move-breaks-references-both-directions]](단방향만 보면 green이지만 깨짐).

### 5. 새 컨트롤은 그냥 붙이지 말고 경계를 세운다(사용자 지시)
"에이전트 설정에 경계 구분을 잘 하라" — 토글을 세부 설정에 平으로 던지지 않고 폼 표준 `SectionHeader`로
모델 동작/저장·영속을 구획하고, ephemeral ON이면 하위 저장 설정을 비활성(무의미 명시). antd v6 Divider
orientation 타입 이슈도 표준 컴포넌트 재사용으로 회피. [[context-control-propagates-to-affordances]].

## 다음에 적용
- 부재(0/없음) 주장 테스트: "무엇의 0"의 목록을 코드에서 열거(도메인 직감으로 좁히지 말 것) + 대조군이
  그 신호를 실제로 내도록 신호원을 켠 뒤 측정. 하네스 자체도 자가검증 → codex에 여집합을 물어라.
- 새 플래그가 "전부 끈다"류 계약이면, 그 계약이 닿는 부수효과 경로(체크포인터·외부 관측·도구)를 전수 열거.
- 구조적 원인 하나로 여러 증상을 닫을 수 있으면 그쪽(견고·회귀 적음).

관련: 스펙 235 · 회고 212(false-green 3종) · [[use-codex-for-adversarial-verification]] · [[installed-guard-isnt-covering-guard]](설치≠커버 — 여기선 _persist 게이트≠전 쓰기경로 커버)
