# 320 — 스펙 392 회고: chat_stream 해체(Command 패턴)와 "자문→습득→실행" 루프

## 무엇을 했나

복잡도 스냅샷이 지목한 최대 성장 지점 chat_stream.py(390줄, 책임 4개)를 개발자 지시대로
**codex 자문 + 패턴 리서치를 먼저** 하고 해체했다. 결과: 4모듈 분리, out-param dict 소멸
(LocalServeTurn Command), 역방향 지연 import 5곳 소멸, 전 게이트 그린 + suite 51/51.

## 배운 것

1. **"자문 먼저" 순서가 설계 품질을 갈랐다.** codex 사전 자문이 위험 오름차순 분할 순서와
   동작보존 함정 6개를 미리 줬고, 패턴 리서치(PEP 525·Parameter Object·Replace Function with
   Command)가 out-param의 근인(제너레이터 반환값 불가)을 이름 붙여줬다. 계획이 "무엇을 조심할지"
   목록을 갖고 시작하니 실행 중 되돌림이 0였다.
2. **스펙 가정은 실행 전 실측으로 갱신된다.** 스펙은 지연 import 3곳으로 썼지만 grep 실측은
   5곳(chat_approval의 _MemoryRecallProxy·_graph_fingerprint 추가) — "전체 정합" 원칙에 따라
   확장했고, 이것이 P4의 실제 가치(순환 0)를 완성했다. 가정 수치는 착수 시 재측정이 기본.
3. **out-param 제거의 진짜 산출물은 타입이 아니라 시간 계약의 명시화.** "소진 후 읽어라"가
   RuntimeError로 강제되자, codex 적대 리뷰도 같은 축(재호출·premature-read·fake 미러 약화)을
   공격했다 — 계약을 명시하면 적대자도 그 계약의 여집합을 정확히 짚어준다.
4. **테스트 fake는 실물 계약의 fail-loud까지 미러해야 한다**(codex P2). fake가 관대하면
   (outcome=None 일반 속성) 소비자 회귀가 fake에서만 통과하는 거짓 초록이 된다 —
   monkeypatch-is-consumer(회고 392계열)의 후속 정리.
5. **suite 도중 --reload 서버에 코드를 넣으면 그 판은 오염된다.** route-branch 실패 1건이
   중간 리로드 오염이었고, 최종 코드로 재실행하니 51/51. 라이브 서버 검증은 코드 동결 후 실행.

## 다음에 다르게

- 리팩터 스펙의 "이동 대상 수" 같은 열거 수치는 계획 단계에서 grep으로 박제(가정 금지).
- 라이브 suite는 편집 완전 종료 후 시작(중간 봉합이 예상되면 표적 verify만 먼저).
