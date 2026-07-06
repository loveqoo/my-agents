# 회고 176 — 노코드 산출물형 에이전트 빌더 (스펙 190)

## 무엇을 했나
스펙 188 코드 뼈대 위에 **노코드 버전**을 얹었다: 범용 `ConfigDrivenArtifactAgent`(NAME=artifact_form)가
에이전트 설정(config.artifactSpec)을 읽어 폼을 돌리고, 어드민 "종류=산출물형"에서 필드 편집기로 그
설정을 만든다. sink=브라우저 콜백(기존 프레임 재사용). 단위+e2e(폼 저작→왕복→플레이그라운드 실행)+
무회귀 3중 그린.

## 배운 것

### 1. 뼈대가 잘 서면 "노코드"는 **설정 통로 하나** 추가로 끝난다
셋째 구현(slot-fill·targeting에 이어)을 붙이는 데 뼈대(@final build_graph/produce_node)를 **한 줄도
안 고쳤다**. 필요한 건 딱 하나 — 에이전트별 설정을 produce까지 나르는 통로(`AgentBuildContext.impl_config`
→ `ProduceContext.config`). "노코드 vs 코드"가 별개 기능처럼 보였지만, 실제론 **같은 뼈대의 produce가
하드코딩이냐 config-읽기냐**의 차이였다. 코드 버전(targeting)은 그대로 남고, 노코드는 "설정을 읽는
범용 produce + 그 설정을 만드는 UI". **교훈: 추상이 제대로 서 있으면 "노코드화"는 새 엔진이 아니라
기존 엔진에 데이터 주입구를 다는 일이다 — 누수0(뼈대 무변경)이 그 증거고, 아니면 추상이 샌 것.**
(회고 173 둘째 구현 규율의 셋째 확인)

### 2. e2e 실패 ≠ 기능 버그 — **스샷으로 "UI 깨짐 vs 셀렉터 틀림"을 먼저 가른다**
노코드 폼 e2e가 두 번 빨갰는데 둘 다 **UI는 멀쩡, 테스트 가정이 틀렸다**: (a) antd Modal은 `#root`가
아니라 **body 포털**에 렌더돼서 `#root` 텍스트 스캔 헬퍼가 편집기를 못 봤고(스샷엔 편집기가 선명히
보임), (b) antd `Select mode="tags"`의 placeholder는 input 속성이 아니라 **오버레이 span**이라
`getByPlaceholder`가 count 0(스샷엔 태그 입력칸 보임). 매번 스크린샷을 먼저 찍어 "화면이 실제로
어떤가"를 확인하니 즉시 갈렸다 — 안 찍었으면 멀쩡한 렌더 코드를 헛디버깅했을 것. **교훈: e2e 빨강이면
단언을 의심하기 전에 스샷으로 실제 화면을 봐라. 프레임워크 렌더 위치(포털)·DOM 관례(placeholder가
어디 붙나)를 테스트가 잘못 가정하는 게 흔하다.** (회고 172 harness-coupled-to-incidentals의 재연 —
이번엔 앱이 아니라 테스트 헬퍼가 프레임워크 세부에 잘못 결합)

### 3. 왕복 보존은 **스키마 3지점**(입력·출력·직렬화)을 다 손대야 안 샌다
artifactSpec이 저장→재로드에서 살아남으려면 AgentConfig(입력)·AgentOut(출력)·agent_to_out(직렬화)
셋 다 추가해야 했다. 하나만 빠져도 model_dump가 조용히 드롭해 폼 재로드 시 명세 소실(learning 101
seed-bypasses-write-schema와 동형). e2e의 P단계(API GET으로 artifactSpec 왕복 확인)가 이 3지점이
다 이어졌는지를 잡는 그물. **교훈: 새 config 필드는 "저장되나"가 아니라 "저장→재로드 왕복하나"로
검증한다 — 왕복 테스트가 직렬화 누락을 잡는다.**

## 다음에 적용
- 새 에이전트 종류/기능: 뼈대 무변경으로 붙는지(누수0)를 먼저 확인, 안 되면 추상 재점검(1).
- e2e 빨강: 스샷 먼저(UI 깨짐 vs 셀렉터 틀림), 포털·DOM 관례 가정 의심(2).
- 새 config 필드: 입력·출력·직렬화 3지점 + 왕복 e2e(3).

관련: [[173-artifact-agent-p1]] · [[174-artifact-agent-p2-p4-adversarial]] · [[172-ui-audit-after-antd]]
