# 396 — "첫 단언만 실패하고 나머지 전부 통과"는 스키마 화석의 서명이다

## 맥락

390이 상향한 "승인 인터럽트 미발동(virgin 재현)" 조사(스펙 391). P0(게이트 우회) 가능성 때문에
최우선 조사했는데, 정밀 판독 결과 **interrupt는 떴고 승인-이전-무실행 불변식도 성립** — 실패는
`permission == "data.delete"` 값 검사뿐(177 P2가 permission을 구조화하고 판정을 approver 필드로
옮긴 스키마 진화의 화석). 단언 현행화로 101·102 그린·격리 -2.

## 교훈

- **실패 요약("interrupt 미발동")이 아니라 판정 목록의 패턴을 읽어라.** H6 첫 단언 실패 직후
  "pause 전송 0·approve 1회·reject 0"이 전부 OK였다 — interrupt가 없었다면 불가능한 통과들.
  복합 단언(`is not None and get(...)==값`)의 실패는 존재 실패와 값 실패를 뭉갠다 — 요약만 보면
  "미발동"으로 오독(384~390 내내 그렇게 기록했다). 복합 단언은 실패 시 어느 절이 죽었는지
  분해해 출력하는 게 좋고, 읽을 땐 주변 판정과의 모순부터 본다.
- **payload 실물 프로브가 종결자다** — 한 번의 자립 프로브(interrupt payload repr)가 3주치
  격리 사유("환경"→"실드리프트"→"스키마 화석")를 한 방에 정정했다. 단, verify를 import하는
  프로브는 모듈 최상위 실행에 낚인다 — 자립형(인라인 상수)으로.
- **단언은 판정 필드로** — 177 P2의 설계("인가는 approver 필드, permission 문자열 매칭 불필요")를
  테스트도 따라야 한다. 값 문자열 단언은 스키마 진화마다 화석이 된다(388 I3b 정확일치 교훈의 재현).
- **P0 의심은 최우선 조사 순위가 맞았다** — 결과가 노후여도, "승인 없이 전송됐나"를 invocations
  수로 즉시 판별할 수 있는 구조(041의 관측 설계) 덕에 배제가 10분에 끝났다. 안전 장치를 검증
  가능하게 설계해 둔 과거의 복리.

[first-fail-rest-pass-is-schema-drift, compound-assert-hides-which-clause,
payload-probe-settles, assert-adjudication-fields-not-strings]
