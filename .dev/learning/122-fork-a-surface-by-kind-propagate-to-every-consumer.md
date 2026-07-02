# 122 — kind별로 표면을 가르면 *모든* 소비 표면에 전파하라 (안 하면 다른 kind 데이터가 조용히 누락)

## 트리거
같은 자원을 **에이전트 종류(kind)별로 다른 필드/표면**에 담기 시작할 때(예: 조율형=capabilities,
직접형=mcps). 그리고 그 자원을 **읽거나 편집하는 표면이 둘 이상**일 때(편집 폼·오버라이드·요약 뷰·API…).

## 사례 (버그2, 스펙 122)
사용자: "조율형 에이전트에 MCP 설정 후 활성화 → 플레이그라운드 오버라이드를 열면 **설정한 MCP가 누락**."
- 원인: 런타임이 이원화([[core-is-model-config-and-memory]] 아님 — learning 108). **조율형은 MCP를
  `config.capabilities`(`mcp:서버`)로** 담고 브로커로 실행, **직접형은 `config.mcps`로** 담고 ctx.tools로
  실행. 스펙 108이 **편집 폼**을 이 kind로 갈랐다(조율형=capabilities 피커, 직접형=직접 자원).
- 그런데 스펙 109가 같은 개선(PickerGroups)을 **오버라이드 패널엔 직접형 필드(mcps/memories)만** 이식
  하고 **조율형 capabilities는 빠뜨렸다**. → `overrideDefaults`가 `agent.mcps`만 읽어 조율형은 빈 값
  → 오버라이드 패널에 MCP가 안 뜸. 런타임은 저장 capabilities를 그대로 써서 **에이전트는 정상 동작**,
  **오버라이드 화면에서만 누락**돼 보이는 미스매치.
- 처방: 오버라이드 패널을 편집 폼과 **같은 kind 분기**로 — 조율형이면 같은 capGroups를
  `draft.capabilities`에 바인딩, 직접형은 기존 mcps/memories. `isOrchestratorImpl`을 mockData로 승격해
  두 폼이 **단일 판정** 공유. 백엔드 오버라이드 허용목록에도 `capabilities` 추가.

## 배운 것
- **표면을 kind로 가르는 결정은 그 자원을 만지는 *모든* 표면에 전파해야 한다.** 한 표면(편집)만 갈리고
  다른 표면(오버라이드)이 예전 단일 모델로 남으면, 안 갈린 표면에서 **다른 kind의 데이터가 조용히
  누락/무시**된다. "동작은 정상, 화면만 틈"이라 happy-path·백엔드 테스트로는 안 잡히고 그 kind로
  그 표면을 실제로 열어봐야 보인다(브라우저 검증이 잡음 — [[verify-ui-in-browser-proactively]]).
- 이건 [[move-breaks-references-both-directions]]의 사촌: **분기(split)도 이동처럼 모든 미러에 퍼져야**
  한다. 한 곳만 바꾸면 나머지가 stale.
- 판정 헬퍼(`isOrchestratorImpl`)를 **단일 소스로 승격**해두면, 다음에 또 다른 표면이 생겨도 같은 분기를
  쉽게 재사용 → 드리프트 예방.

## 보안 메모 (confused-deputy 비대칭)
capabilities를 오버라이드 허용목록에 넣어도 **confused-deputy(스펙 113) 없음**: 브로커가
`build_broker(principal=호출자, capabilities)`로 `_permitted = allowlist ∩ 호출자 RBAC`를 닫는다 —
저장분이든 주입분이든 항상 호출자 스코프. 반면 `mcps`는 실제 tool wiring에서 암호화 토큰을 복호화해
붙이므로 저장분=작성자/주입분=호출자 게이트가 필요(stored_mcps 분기). **"오버라이드 가능 자원마다
최종 권한이 어디서 닫히나"를 확인**하면 게이트 필요 여부가 갈린다(정책-스코프 vs 자격증명-배선).

## 곁다리 (codex P3)
`OverridePanel.tsx`의 pre-existing `sameSet`이 `join('\0')`(NUL 구분자)이라 **git이 파일을 바이너리로
취급** → diff가 비고 코드리뷰 도구가 변경을 못 봄. 소스에 NUL 제어문자는 검토성을 깬다 — 집합비교
구분자는 값에 안 나오는 **printable/개행**(`'\n'`)으로. (자원명·cap id엔 개행 없음.)
