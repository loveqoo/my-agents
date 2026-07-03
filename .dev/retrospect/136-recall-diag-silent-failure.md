# 136 — 회상 진단이 실패를 "정상·0건"으로 위장하던 버그 (스펙 158)

자율 루프 9건차(실사용, C 시리즈 진입 전 사용자 지정 버그 "메모리 있는데 유사도 검색 안 됨").

## 증상→근인
사용자 다른 배포본: 스코프에 기억 11건 있는데 회상(유사도 검색) 0건, 진단은 "정상·백엔드 준비됨·
error 없음". 텍스트 목록(SQL)은 되고 벡터 유사도만 0.

내 첫 가설은 **M1(예외 삼킴)** — `Mem0Backend.search`가 축별 `except: continue`로 전 축 실패도
[] 반환 → recall_diag가 error 못 봄. 실재하는 결함이나, deep-reasoner가 mem0 소스를 읽어 **진짜
주범 M2**를 찾음: **mem0 2.0.7 `search`의 숨은 기본 `threshold=0.1`**. 우리가 이 인자를 안 넘겨 상속
→ 코사인 유사도<0.1인 기억을 전부 컷(scoring.py) → **0건·예외 없음**. arctic-embed는 query prefix가
필요한 비대칭 모델인데 mem0가 prefix 미주입 → 유사도가 더 눌림. M1·M2가 **완전히 같은 화면**을
만들어 스크린샷만으론 구별 불가.

## 배운 것
- **두 실패 모드가 같은 화면을 만들면 "예외를 표면화"만으론 안 고쳐진다.** M2는 예외가 아니라 정직한
  임계 컷이라 A/B/C(예외 raise·표면화)가 무력. 진짜 수정은 **회상 테스트가 UI 약속("관련도 내림차순
  상위 기억")대로 top-k를 threshold=0으로 보여주는 것** — 그러면 낮은 점수(0.016·0.0)까지 노출돼
  사용자가 "0건"이 아니라 "유사도가 낮다"를 보고 원인(임베더/질의)을 자가진단한다. 진단의 정직성은
  "실패를 에러로"만이 아니라 **"약속한 것을 실제로 보여주기"**도 포함.
- **라이브러리의 숨은 기본값을 의심하라.** 우리 코드 어디에도 threshold가 없어 "필터 없음"이라 착각
  했는데, mem0가 0.1을 숨겨 상속시켰다. 차원(1024) 일치·필터 SQL 일치를 다 확인하고도 0건이면
  **의존 라이브러리의 기본 인자**가 남은 용의자 — 소스를 읽어야(deep-reasoner) 나온다. 추측 금지.
- **파사드 3분기 실패 계약**: 같은 코어(backend.search)라도 소비 맥락마다 실패를 다르게 다뤄야 정직.
  챗=조용한 [](대화 안 죽음), 브로커=InvokeResult.error(0건 위장 금지, error 채널 있음), 진단=표면화.
  "전부 []로 접기"는 recall_probe가 애초에 막으려던 위장을 재발시킨다.
- **마스킹은 응답만이 아니라 로그까지**(codex High). 응답 error는 _sanitize로 가렸는데 `log.warning
  ("...%s", exc)`가 raw 예외(임베더 api_key 섞임)를 로그로 흘렸다. 예외 메시지를 로그할 땐 `type(exc)
  .__name__`만 — 상세는 마스킹된 진단 응답이 담는다. 검증도 응답 텍스트만 보지 말고 **로그 캡처로 측정**.
- **파생 진단 필드는 두 입구 모두에**(codex Med). stored를 유저 메모리 라우트에만 매핑하고 에이전트
  메모리 라우트(agents.py)엔 빠뜨림 → 공유 UI가 한쪽에서만 표시. 같은 diag를 쓰는 라우트는 grep해 동형화.
- **로컬 재현 = mock-embed의 성질을 역이용**. mock-embed는 텍스트별 독립 난수 벡터라 서로 다른
  텍스트의 코사인 유사도≈0 → 0.1 미만이 **결정적** → 사용자의 "저장>0·회상0"을 로컬에서 그대로 재현.
  임베더가 없어 못 한다고 단정하지 말 것 — mock의 특성이 곧 M2 재현 장치.

## 검증
verify_158 12/12(M1 표면화+마스킹·M2 재현/수정·부분성공 무예외·챗견고·브로커전파·로그 비밀 미노출
V3b/V5c). e2e PASS(K2 API: results 3·stored 3·count 3 — 수정 전 0건이었을 상황). deep-reasoner 근인
확정(중, M2 유력). codex High1(로그누출)/Med1(agents.py stored) 전부 반영·측정.

## OUT(후속)
- arctic query-prefix 임베더 계층 주입·재인덱싱 도구·챗 회상 threshold 튜닝(제품 결정). 이 스펙은
  **진단/테스트 경로 정직화**가 범위. mem0의 숨은 0.1을 챗도 상속하므로 저유사도 기억은 챗도 조용히
  회상 안 함 — 진단이 이제 이를 드러내니 후속 튜닝의 근거가 생김.

[recall-diag,hidden-library-default,two-failure-modes-same-screen,honest-diagnostic-shows-promise,facade-three-way-failure-contract,mask-logs-not-just-response,mock-embed-reproduces-low-similarity]
