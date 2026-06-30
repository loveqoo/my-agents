# 087 — 상태 표시값은 *프록시*가 아니라 *실제 가용성*에 묶어라 ("구성됨 ≠ 작동함")

**언제**: API가 어떤 하위 기능(메모리·검색·외부백엔드·캐시)의 가용 여부를 `enabled`/`available`/
`healthy` 같은 **상태 플래그로 응답에 실어 내릴 때**. 특히 그 기능의 *팩토리/리졸버가 초기화
실패를 흡수*(try/except→None 캐시·빈 객체 폴백)하는 경우.

**무엇이 비자명한가**: "구성됐냐"(설정값 존재)와 "작동하냐"(백엔드 실제 생성·응답)는 **다른 축**이다.
- `enabled = (config is not None)`은 *프록시*다 — 설정은 있는데 백엔드 구성이 실패(키 누락·연결
  불가·리졸버가 None 흡수)하면 플래그는 True인데 결과는 항상 0건. → **"고장/미구성"을 "가용·결과
  0건"으로 위장**. 시험·디버그 도구일수록 치명(그 도구의 존재 이유가 "실제로 되는지 확인"이라).
- happy-path 테스트엔 안 잡힌다(설정 있음→True→통과). **적대 리뷰가 "구성됐으나 깨진 백엔드"를
  여집합으로 시키거나, 사용자가 "되는 것처럼 보이는데 안 됨"으로 먼저 짚는다**(086과 동형 증상).

**처방**:
1. **플래그를 *실제 가용성*에 묶는다** — 설정 존재가 아니라 *리졸버/팩토리 결과*로 판정
   (`backend = resolve(); enabled = backend is not None`). 리졸버가 초기화 실패를 흡수하면 그
   None이 곧 "미가용" 신호가 되게 한다.
2. **3-값 구분을 유지** — None(미가용/미구성) ≠ [](가용·결과 0건). 프런트가 "비활성 안내"와
   "결과 없음"을 다르게 그릴 수 있어야 한다. 둘을 [](또는 0)로 뭉개면 정보 손실.
3. **얇은 facade로 격리** — 기존 핵심 경로(여기선 chat의 `search`)를 건드리지 말고 *시험용
   probe* 함수를 따로 둬 가용성 구분+방어적 출력 상한(`[:limit]`)을 거기서만. drift 0.
4. **회귀 핀**: "설정 있음+백엔드 None→enabled=False"를 명시 단언(프록시 회귀 방지), None vs []
   구분도 별도 단언.

**연결**: 086(소비층 fail-closed만으론 *죽은 상태*가 샘 — capability *술어*를 모든 입구에 정렬)과
같은 결의 다른 축 — 086은 동작 술어, 087은 *상태 표시값*. 둘 다 "겉도는/거짓 신호"를 닫는다.
"설치/구성됨 ≠ 덮음/작동함"은 보안가드(installed-guard)·probe-deeper와도 공명: 한 겹 더 파라.

[status-flag,proxy-vs-actual,configured-not-working,resolver-absorbs-failure,three-valued-none-vs-empty,thin-facade,no-drift,defensive-output-bound,adversarial-codex,probe-deeper,086-sibling-axis]
