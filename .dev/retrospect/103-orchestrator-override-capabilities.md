# 103 — 회고: 조율형 오버라이드 capabilities 반영 (스펙 122, 버그2)

## 무엇을 / 왜
사용자 버그2: "조율형 에이전트에 MCP 설정 후 활성화 → 플레이그라운드 오버라이드를 열면 설정한 MCP가
누락." 원인은 표면 분기 누락: 스펙 108이 편집 폼을 kind별로 갈랐으나(조율형=capabilities), 스펙 109가
오버라이드 패널엔 직접형(mcps/memories)만 이식해 조율형 capabilities가 빠졌다. 오버라이드 패널을
kind-aware로 고치고(capGroups 바인딩), 백엔드 허용목록에 capabilities 추가.

## 잘된 것
- **런타임 이원화(learning 108) 지식으로 원인을 바로 특정** — "왜 MCP가 mcps가 아니라 capabilities인가"를
  추측 없이 코드로 확인(chat.py 오버라이드 허용목록에 capabilities 없음 + OverridePanel이 mcps만).
- **판정 헬퍼 단일 소스화**: `isOrchestratorImpl`을 mockData로 승격, AgentsView·OverridePanel 공유 →
  또 다른 표면이 생겨도 같은 분기 재사용(드리프트 예방).
- **보안 비대칭을 명확히**: capabilities는 브로커가 항상 호출자 RBAC로 닫아 confused-deputy 없음(mcps의
  stored-vs-injected 게이트 불필요). codex가 이 논리를 독립 확인.
- **브라우저 검증이 결정적**: 백엔드 verify_122(6/6)만으론 "화면 누락"을 못 잡는다. Playwright로 조율형
  오버라이드를 실제로 열어 "이 대화에서 맡길 것"에 MCP가 **체크된 상태**로 뜨는 걸 스샷 확인(H2~H4).

## 아쉬운 것 / 리스크
- **codex P3로 pre-existing NUL 발견**: `sameSet`의 `join('\0')`이 파일을 git 바이너리로 만들어 내
  bug2 diff에서 OverridePanel이 통째로 빠졌었다(codex는 파일 직접 읽어 리뷰). 개행 구분자로 교체해
  복구 — **비-ASCII/제어문자 소스는 diff·리뷰 파이프라인을 조용히 깬다**는 교훈.
- 카탈로그 밖(미등록) capability는 패널에 안 뜸(OUT). 저장분은 오버라이드 미전송 시 런타임이 그대로
  사용하므로 실동작 누락은 없음.

## 다음 작업 Context에서 상기할 것
- 자원을 kind별로 가르면 **편집·오버라이드·요약 등 모든 소비 표면**에 같은 분기 전파(learning 122).
- 오버라이드 가능 자원 추가 시 **최종 권한이 어디서 닫히나** 확인 → 게이트 필요 여부 판정.
- "동작 정상, 화면만 틈" 버그는 **그 kind로 그 화면을 실제로 열어야** 보인다(브라우저 검증 우선).
- 참고: learning 122, [[verify-ui-in-browser-proactively]], learning 108.
