# 085 — 능력 브로커 kind 확장: Memory provider (Phase 2-c, 첫 per-user 소유 능력)

스펙 104. 능력 브로커에 네 번째 provider(kind=memory, 유저 장기 기억 검색)를 붙였다. 앞선 셋
(agent·mcp·rag)은 전부 **주인 없는 공유 카탈로그**라 cap_id에 대상을 박아도 됐다. 메모리는 처음으로
**per-user 개인 데이터**라, learning 100/retrospect 081이 "미룬 빚"으로 기록한 **인가 입도**를 이번엔
선행해서 갚아야 했다.

## 무엇을 했나

- `MemoryProvider`(kind=memory)를 `broker.py`에 추가. 능력은 `memory:user` **하나뿐**. RagProvider를
  거울삼아 6메서드 시임 계약 그대로 구현.
- **핵심 뒤집기**: cap_id에 대상 user를 박지 않는다. 누구의 기억인지는 **런타임 principal에서 도출한
  user_id**로 정한다 — `build_broker`가 `str(principal.id)`를 뽑아 `MemoryProvider`에 주입, invoke의
  스코프는 **오직** `{"user_id": self._user_id}`(cap_id·args 불가). 능력 이름으로 남을 가리킬 방법이
  없어 교차 유출이 *구조적으로* 불가능.
- **정책은 손 안 댐**: `_permitted` memory 분기 0줄(rag처럼 1레벨 정확 매치). 정책은 정말 provider와
  분리돼 있었다(네 번째 provider가 또 측정).
- **코어 재사용**: invoke는 `memory.recall_probe`(챗 회상·retrieval 시험 084와 공유) + 챗 회상 주입
  포맷을 `format_memory_hits`로 추출해 공유(103 format_rag_hits 방식). 읽기 전용 → `approval_for` None.
- 검증 사다리 3런: verify_104(FakeMem 단위 결정적 격리 + 실 mem0·실 DB 통합, all pass) + 무회귀
  (084/100/101/102/103) + codex 적대 리뷰.

## 잘된 것 — 두 게이트 분리가 또 벌었다

- **읽기 전용이라 통합이 쌌다**: `approval_for=None` 한 줄로 HIL 우회, 그러나 정책은 완전 적용
  (learning 103 두 게이트 분리 재확인).
- **교차유저 격리를 두 층위로 실증**: FakeMem(단축 필터 mock)로 결정적으로 — 같은 cap·같은 store,
  주체만 bob↔alice로 바꾸면 결과가 갈린다. + 실 mem0로 같은 격리를 실 backend 필터가 지키는지(H3).
  "빚 상환"의 핵심 증거가 수치로 남았다.
- **anti-leak을 세 각도로**: cap_id(리소스만·대상 없음)·args(`user_id` 밀반입 무시)·principal(유일 출처).
  codex가 셋 다 공격했고 셋 다 실패(오탐 기각).

## codex 적대 리뷰 — 3판정 (P0/P1 없음, P2 3건)

- **[P2 실결함] limit 타입 미검증** — 브로커가 `args.limit`를 무검증 전달해 `{"limit":"boom"}`→TypeError.
  103 P2(질의 무제한)와 **동형의 교차입구 갭**. → `recall_probe`에 정수 강제+clamp(084가 이미 limit
  방어 슬라이스를 둔 지점 = 공유 지점, learning 103). *예측하고 있던 결함*이지만 codex가 정확히 짚음.
- **[P2 실결함] 승인 재개 브로커 user_id 누락** — 내가 놓친 배선. `_build_resume_broker`가 user_id를
  받고도 `PolicyScopedBroker`에 안 넘겨, 승인 재개 시 `memory:user`가 사라짐(fail-closed지만 자기 기억
  접근이 재개서 깨지는 회귀). → `user_id=user_id` 주입. **새 상태 축(user_id)을 배선하면 그 축을 쓰는
  *모든* 배선 지점을 찾아야 한다** — request-time(build_broker)만 고치고 resume-time을 놓쳤다.
- **[P2 미문서 경계] format_memory_hits는 격리 장치 아님** — 순수 문자열 결합. 브로커 경로는 flow가
  데이터 채널로 감싸(learning 100) 격리하지만 챗 직접 회상은 persona에 주입(104 이전 설계). 자기
  기억이라 교차유저 인젝션은 아님. → docstring 강화 + 스펙 비목표 명시(complement→honest boundary,
  learning 100/102 재적용).

## 아쉬웠던 것 / 다음

- resume 배선 누락은 happy-path(단일 턴)에선 안 보였다 — 승인 interrupt가 걸린 멀티턴에서만 드러난다.
  codex가 request/resume 두 경로의 *대칭성*을 봤다. 새 생성자 인자를 더하면 그 인자를 만드는 *모든*
  팩토리(build_broker + _build_resume_broker)를 세는 습관을 체크리스트 §1(입구 열거)의 배선판으로.
- 다음 축: memory **쓰기**(add) 능력 — 승인 게이트(정책 O + 승인 O, 두 게이트 다)가 처음 필요한
  provider. 과거 자동쓰기 누출(051)이 있어 쓰기 채널 재개는 별도 누출 분석 선행. 백로그 Phase 2 (a)로.

관련: learning 104 · learning 100·101·102·103 · [[complement-attack-can-be-honest-boundary]] · 스펙 104.
