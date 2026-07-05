# 159 — mock 도구 트리거로 HIL 승인 대화 실습

**스펙**: docs/spec/179-mock-tool-trigger-for-hil-demo.md · **관련**: 스펙 041(HIL 게이트), 177(승인 정책), verify_041

## 무엇을 했나
mock 챗 모델(`mock_remote.py`)이 **도구 호출을 미지원**(평문만)이라, 승인 게이트 대상 도구
(`local-tools.delete_record`)를 플레이그라운드 대화로 트리거할 수 없었다. mock에 **개발용 도구 트리거**를
달아(바인딩된 도구 + 트리거 키워드 매치 → 결정적 `tool_call`), 실모델·외부키 없이 HIL 승인 흐름을
대화로 실습 가능하게 했다. e2e로 delete_record 어드민 승인(채팅→승인대기→승인→실행) 실증.

## 무엇이 잘못됐고 무엇을 배웠나

### 1. 단위 테스트 더블이 라이브 shape와 달라 false green (핵심)
`_pick_tool_call`을 만들고 단위 테스트를 `tools:[{name:"delete_record"}]`(bare 이름)로 짜서 **12/12
초록**. 그런데 플레이그라운드 e2e에선 도구가 **안 불리고 평문**만 나왔다. 원인: 그래프가 바인딩하는
실제 도구명은 **네임스페이스가 붙어 `local-tools__delete_record`**인데, 내 매칭은 bare `delete_record`
정확일치라 불발. 내 단위 테스트가 bare 이름을 써서 라이브와 다른 shape를 검증 → 통과가 거짓 안심.

- **처방**: 테스트 더블은 **라이브의 실제 형태**를 써라. 여기선 `build_mcp_tools`를 라이브로 태워
  실제 이름(`local-tools__delete_record`)을 확인하고, 매칭을 suffix(`__{tool}`)로 고치고 tool_call을
  **실제 바인딩명으로 emit**(라우팅 정합), 네임스페이스 케이스를 테스트에 추가(T7). 이게 검증 사다리의
  이유 — 단위(시맨틱)만으론 라이브 통합이 잡는 shape drift를 못 본다([[verification-ladder-three-rungs]]).
- **일반화**: "내가 만든 입력"으로만 테스트하면 내가 상상한 형태만 검증한다. 경계에서 실제로 흐르는
  값(네임스페이스·인코딩·래핑)을 한 번은 라이브로 확인해 더블을 그 모양에 맞춰라.

### 2. 슈퍼유저로는 "본인(self) 승인"을 경험할 수 없다 (설계상)
`_may_resolve`: approver=admin은 관리자만, self는 요청 owner 본인. **슈퍼유저는 is_privileged라 무엇이든
승인** → self-approve 분기를 절대 안 탄다. 즉 "본인 승인"을 실습하려면 **member(비특권) 계정**이 필요
하고, 그 계정으로 self-approvable 액션(memory.write, 또는 delete_record approver=self 오버라이드)을
일으켜야 한다. 권한 데모는 "어떤 역할로 로그인했나"가 곧 시나리오다 — 관찰자 계정 등급을 먼저 정하라.

### 3. mock에 새 행동을 넣을 땐 기존 계약을 가드로 보존
mock은 여러 테스트가 "평문 1턴"을 전제한다(mock_remote.py 원주석). 트리거를 **바인딩된 도구 + 키워드
매치 + 히스토리에 tool 결과 없음** 3조건으로 좁혀, 평상 채팅은 기존 평문 그대로(무회귀). 재개 후 턴
(role=tool 존재)은 평문으로 빠져 무한 tool_call 루프도 차단. 데모용 훅은 happy-path만 열고 기존은 봉인.

## 복리 포인트
- HIL 승인이 이제 **플레이그라운드에서 재현 가능** — 정밀 디버그 통로가 승인 흐름까지 커버
  ([[playground-is-precision-debug-channel]]). 실모델 없이 데모/회귀 e2e 가능.
- 어드민 승인 e2e는 브라우저로 증명, 본인 승인은 member 계정이 있어야 실습(설계 귀결) — 사용자에게
  계정 등급별 시나리오로 안내.
