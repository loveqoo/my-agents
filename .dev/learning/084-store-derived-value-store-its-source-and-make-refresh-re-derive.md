# 084 — 파생값을 저장하면 그 *출처*도 저장하고, refresh 경로가 타임스탬프가 아니라 *재파생*하게 하라

## 상황
외부 A2A 에이전트 채팅이 "외부 에이전트 응답 오류 404"로 실패. 저장된 `endpoint`는 Agent Card에서
*resolve된 파생값*이다(스펙 071: 프록시 path-prefix 카드의 루트상대 `/a2a`를 prefix 하위로 보정).
071이 resolution 로직을 고쳤지만 그 보정은 **fetch_card 시점에만** 걸려, 071 이전 등록분·원격이 바뀐
분의 stale endpoint는 그대로 남았다. "재동기화"(resync) 버튼은 있었지만 `last_sync="방금"`만 찍는
**표시용 no-op** — 파생을 다시 계산하지 않았다. 즉 파생값이 굳은 채, 그걸 새로 만들 경로가 없었다.

## 배운 것 (일반화)
- **파생값을 컬럼에 영속하면 그 값은 *시점 스냅샷*이다.** 파생 규칙이 나중에 개선되거나(우리 코드 변경)
  원천이 원격에서 바뀌면(외부 변경), 저장된 파생값은 stale해진다. 마운트 1회 페치가 탭 밖 변경에 stale해지는
  것(learning 083)과 같은 병 — 083은 UI 소비 표면의 *시간축*, 084는 **영속 저장의 시간축**이다.
- **그래서 두 가지가 같이 필요하다**: (1) 파생의 **출처를 함께 저장**한다(여기선 카드 출처 URL=cardUrl).
  출처가 없으면 재계산할 입력이 없어, "삭제 후 재등록"이라는 사용자 수작업으로만 고쳐진다. (2) **refresh
  경로가 실제로 재파생**하게 한다 — `last_sync`만 갱신하는 "리프레시"는 *리프레시처럼 보이는 no-op*이다.
  재fetch→재resolve→파생 컬럼·상태 갱신까지 해야 진짜 자가치유다.
- **"보정 로직을 고쳤다"≠"이미 굳은 값들을 고쳤다".** 새 입력에만 적용되는 수정은 *유입*을 막을 뿐
  *재고(在庫)*는 그대로다. 잔존 stale을 닦는 별도 경로(마이그레이션 또는 on-demand 자가치유 resync)가
  없으면 사용자는 "고쳤다는데 내 건 그대로"를 겪는다(스펙 063의 endpoint 정규화 마이그레이션과 같은 짝).
- **재파생은 기존 행 in-place 갱신, 새 생성 아님.** id·소유·버전을 보존해야 한다(connect의 새 Agent 생성과
  다름). 출처에서 못 받아오면(fetch 실패) 등록을 지우지 말고 **status만 정직하게 offline**(045 #2).
- **출처는 신뢰경계 안의 것만.** 재fetch는 *우리가 등록 때 사용자 입력으로 받아 guard 통과한* cardUrl에서만 —
  request Host 등 외부 파생 입력을 재파생 입력으로 쓰면 host-poisoning이 열린다([[move-breaks-references-both-directions]]
  의 신뢰경계 원리, learning 064). guard_url은 재파생 경로에서도 fetch_card·probe가 각각 선행.

## 어떻게 적용하나
컬럼에 *다른 데이터에서 계산한 값*(resolve된 URL·요약·정규화·캐시·플래튼)을 저장할 때:
① 이 값의 **출처(입력)를 재계산 가능하게 저장했나?** 안 했으면 출처 컬럼/키를 같이 추가한다.
② 이 값이 stale해지는 두 경로를 본다 — **우리 규칙 변경**(다음 배포가 더 잘 계산)·**원천 변경**(원격이 바뀜).
③ "refresh/resync/sync" 액션이 있으면 **타임스탬프만 찍는지 진짜 재파생하는지** 확인 — 전자면 가짜 리프레시다.
④ 재파생은 **in-place**(id·소유·버전 보존), 출처 도달 실패는 **상태만 정직**(삭제 금지).
⑤ 이미 굳은 재고가 있으면 **마이그레이션 또는 on-demand 자가치유**로 닦는다(유입 수정만으론 재고가 남음).
⑥ 재파생 입력은 **신뢰경계 안**(guard 통과한 저장값)에서만, 외부 파생 입력 금지.

## 근거
- 스펙 081: connect/external이 `config["cardUrl"]` 저장(`_build_*_agent`에 card_url 인자). `resync_agent`가
  cardUrl 있으면 `fetch_card`(071 resolution 재실행)→`probe_endpoint`→endpoint·`config["card"]`·status
  in-place 갱신, 없으면(레거시) last_sync만+재연결 안내, fetch 실패면 offline 정직. JSONB는 `agent.config=cfg`
  재할당으로 더티 표기(in-place 변이 미추적).
- 검증 verify_081_live ALL PASS 8: connect cardUrl 저장→endpoint 손상→resync 교정(want=prefix/a2a)→status
  online→교정 endpoint로 호출 텍스트 도달→레거시(cardUrl strip) no-op+last_sync. 통합 rung만이 이 글루를 잡음.
- 관련: 071(resolution 자체)·063(endpoint 정규화 *마이그레이션*=재고 청소의 짝)·083(소비 표면 시간축,
  084는 영속 저장 시간축), [[probe-deeper-before-concluding]](전달 리포트의 C 1순위를 B로 재분별),
  memory: cap-the-raw-source(폴백 분기 무경계 read 제거).
