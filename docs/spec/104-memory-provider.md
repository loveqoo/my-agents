# 104 — 능력 브로커 kind 확장: Memory provider (Phase 2-c, 첫 per-user 소유 능력)

## 배경 / 왜

능력 브로커(스펙 100)는 `discover/describe/invoke` 한 시임에 여러 kind를 얹는다. 지금까지 붙인
provider는 셋 다 **주인 없는 공유 카탈로그**였다:

- agent(100)·mcp(101)·rag(103) — 자원이 누구 것도 아니라, cap_id에 대상을 박아도(`rag:회사문서`)
  누구에게 노출되든 같은 데이터다. 그래서 정책은 `에이전트별 allowlist ∩ kind-단위 RBAC` 한 겹으로
  충분했다.

learning 100 / retrospect 081이 이 구조의 **입도 한계**를 명시 경계로 기록했다: "Agent엔 owner가
없어 공유 카탈로그라 per-cap·per-user를 못 막는다." 이건 우회가 아니라 kind가 공유형이라 생긴 한계다.

**메모리는 다르다 — user_id 축의 장기 기억은 per-user 개인 데이터다.** 여기에 공유 카탈로그 방식을
그대로 쓰면(cap_id에 대상 user를 박으면), 능력 이름 `memory:앨리스`를 allowlist에 넣은 에이전트를
**밥이 실행하면 밥이 앨리스 기억을 읽는** 교차 유출이 난다. 103이 "미룬 빚"(retrospect 084)이 이것 —
메모리 provider는 **인가 입도(per-user 소유권)를 선행 강제**해야 붙일 수 있다.

## 핵심 설계 — 소유권을 cap_id가 아니라 실행 주체에서 뽑는다

**규칙을 뒤집는다: 능력 이름에 대상 user를 박지 않는다.** 능력은 하나뿐이다:

```
memory:user   ← "지금 이 능력을 실행하는 주체 자신의 장기 기억을 검색"
```

누구의 기억인지는 **cap_id도 args도 아닌, 런타임 principal(로그인 주체)**에서 그때그때 도출한다:

- `build_broker(principal, allowlist)`가 이미 principal을 받는다. 여기서
  `uid = None if isinstance(principal, str) else str(principal.id)`를 뽑아 `MemoryProvider(session_factory, uid)`로 주입.
- invoke의 스코프는 **오직** `{"user_id": self._user_id}` — cap_id·args의 어떤 필드도 user_id를
  지정하거나 덮어쓸 수 없다.

이러면 **이름으로 남을 가리킬 방법 자체가 없어져** 교차 유출이 *구조적으로* 불가능하다. 이것이 이 스펙이
증명할 per-user 인가 입도다. (checklist §2d "비-SQL 저장소는 호출 자체에 owner를 묶는다"의 정공법 —
mem0는 전역 id·공유 pgvector라 SELECT-WHERE가 불가하니, owner를 *스코프 filter에* 묶어 그 유저 행만
로드한다.)

**어드민도 예외 없음(에스컬레이션 차단):** superuser가 `memory:user`를 실행해도 스코프는
`{"user_id": 그 어드민의 id}` — 자기 기억만 나온다. 어드민의 타인 큐레이션 권한(`memory:manage`)은
URL에 대상 user_id를 받는 **별도 경로**(memory_routes, 스펙 053)이지 위임 능력이 아니다. 브로커 메모리
능력은 대상 인자를 애초에 받지 않으므로 주체가 누구든 항상 self.

## 두 게이트 (learning 103)

- **정책 게이트**(allowlist ∩ kind-RBAC ∩ deny-by-default ∩ 존재비노출): 적용됨. 다른 provider와 동일하게
  `_permitted`가 브로커 단일 지점에서 판정. memory는 1레벨이라 mcp의 서버-전체 특례 불요 → 기본
  `cap_id in allow` 경로. `_permitted`에 memory 분기 0줄(정책은 provider와 분리).
- **승인 게이트**(`approval_for` → HIL): **읽기 전용이라 항상 None**. 검색은 비가역 부수효과가 없다.
  (memory read = 정책 O / 승인 X. memory *write*는 정책 O / 승인 O이나 이 스펙 밖 — 아래 비목표.)

## 구현

### cap_id 네임스페이스
- `CAP_KIND_MEMORY = "memory"`, 접두 `memory:`(kind 문자열 == 접두, rag/mcp 관례와 동일).
- `_kind_of`: `memory:`로 시작하면 memory. agent/mcp/rag 무회귀.
- `_parse_mem(item) -> str`: `memory:` 벗겨 리소스 반환(첫 출하는 `"user"`만 유효). 빈 리소스는 거부.

### MemoryProvider (broker.py, RagProvider 거울)
생성자 `MemoryProvider(session_factory, user_id)` — user_id는 build_broker가 principal에서 도출해 주입.
6메서드 시임 계약:
- `candidates(allow)`: `memory:user`가 allow에 있고 **user_id가 있을 때만** 정적 Capability 1개 반환
  (가상 자원 — DB 카탈로그 행 없음, hook="내 장기 기억 검색"). user_id None(머신) → `[]`(DB 미접촉).
- `load(cap_id)`: `_parse_mem`이 `"user"`가 아니거나 user_id None → None(존재 비노출). else 경량 backing.
- `describe(row)`: input_schema `{text: required, limit: int default 4}`. **user_id 필드 없음**(주체 고정).
- `invoke(row, args)`: mem_cfg = `default_mem_cfg(session)`; `memory.recall_probe({"user_id": self._user_id}, text, mem_cfg, limit)`.
  - `hits is None`(백엔드 미가용) → graceful error(에이전트 안 죽임, 084 recall_probe 정직성 계약 재사용).
  - else `format_memory_hits(hits)`로 텍스트화, `trust="untrusted"`(기억 내용 = 데이터, learning 100).
  - **args의 어떤 필드도 user_id로 쓰지 않는다** — self._user_id만.
- `node_label(row)`: `broker_invoke:memory:user`.
- `approval_for(cap_id, args)`: None.

### 공유 텍스트 포맷터 (drift 0, 103 방식)
chat.py 회상 주입의 인라인 포맷 `"\n".join(f"- {h['text']}" for h in mem_hits)`을
`memory.format_memory_hits(hits) -> str`로 **추출**해 chat 회상 + 브로커 invoke가 공유.
(검색 코어 `memory.search`/`recall_probe`는 이미 chat·/search 엔드포인트가 공유 중 — retrieval core drift 0.)

### 배선
- `build_broker`: principal에서 uid 도출 → `PolicyScopedBroker(allowlist, rbac_allows, session_factory=…, user_id=uid)`.
- `PolicyScopedBroker.__init__`: `user_id=None` kwarg 추가, providers에 `MemoryProvider(session_factory, user_id)` 등록.
  agent/mcp/rag provider는 무변경(user_id 불필요).

## RBAC / 소유권 경계 체크리스트 (docs/spec/CLAUDE.md 발동 — 메모리=유저별 데이터)

1. **입구 열거(닫힌 집합)** — 브로커 메모리 입구 = **{discover, describe, invoke}** 뿐. 읽기 전용이라
   create/update/delete/resume/lazy-create 입구 없음. 외부 프로토콜(A2A) 입구는 브로커가 유저 세션 flow
   안에서 도므로 머신 principal은 deny. 기존 memory_routes CRUD(053에서 이미 스코핑됨)는 이 스펙 밖.
2. **입구별 소유권** — 읽기(discover/invoke): owner 스코프 user_id를 mem0 filter에 밀어 그 유저 기억만
   로드(§2d 비-SQL: 호출에 owner를 묶음). user_id는 principal 도출값, **cap_id·args 불가**. 쓰기/resume/
   생성 입구 없음.
3. **단일 헬퍼** — user_id 도출은 build_broker 한 곳, 스코프 dict 구성은 invoke 한 곳(drift 0).
4. **존재 비노출** — allow 밖 → `_permitted`가 load 이전에 not-found. 머신(user_id None)·비-user 리소스 →
   candidates `[]`·load None으로 접음(403/404 구분 안 함).
5. **검증 사다리 3런(비겹침)**:
   - ① **단위 시맨틱**: `_kind_of`/`_parse_mem` 네임스페이스(agent/mcp/rag 무회귀), `_permitted` memory,
     approval_for None, describe 스키마(text required·user_id 필드 부재), candidates가 allow∩user_id 게이트,
     머신→[], `_by_kind`에 memory, 시임 6메서드+node_label, **invoke가 args의 user_id를 무시**(주입값만).
   - ② **실 인프라 통합(seed+restart)**: 실 mem0 백엔드. **앨리스·밥 기억 각각 시드.** 에이전트 allowlist=
     `memory:user`. **빚-상환 핵심 테스트**: 밥으로 invoke → **밥 기억만**, 앨리스 기억 절대 안 나옴(cap 문자열
     동일한데도). + discover가 memory cap 노출·describe·invoke 텍스트 포맷·`broker_invoke:memory:user` 프레임·
     trust=untrusted·RBAC-deny→discover []·머신 principal→deny·백엔드 미가용→graceful.
   - ③ **적대 타자(codex)**: 보장 목록의 여집합 — args/cap_id로 타 user_id 밀반입 가능한가? 머신이 닿는가?
     빈 스코프가 전체 유출인가? 어드민 에스컬레이션?
6. **자가-잠금 핀** — 밥은 브로커로 **자기** 기억을 정상 검색 가능(조임이 정당한 self-access를 막지 않음).

## 완료 조건 (측정 가능)

- verify_104_broker_memory: 단위(순수) + 실 mem0·실 DB 통합, **교차유저 격리(cap 동일·주체만 다름 →
  결과 분리)**를 수치로 실증, all pass.
- 무회귀: verify_100/101/102/103 + 메모리 관련(존재 시) 통과.
- codex 여집합 리뷰 3판정(실결함 수정 / 오탐 기각 / 미문서 경계 명시) 완료.
- 회고 085 + learning 104 + INDEX 3종 + 백로그 갱신 + per-spec 커밋(푸시/머지 없음).

## 비목표 (OUT — 다음 스펙)

- **메모리 쓰기(add) 능력** — 승인 게이트(정책 O + 승인 O) 필요 + 과거 자동쓰기 누출(스펙 051·learning 041)
  이력이 있어 쓰기 채널 재개는 별도 누출 분석을 요구. 이 스펙은 읽기만.
- **agent_id 메모리(어드민 저작 지식)를 공유-카탈로그 읽기 능력으로**(`memory:agent:<id>`) — 가능하나
  agent_id 회상 축별 합집합 누출 이력(041)이 있어 별도 분석 후. 이번은 user_id 축만.
- **run_id 세션 단기 기억** — 휘발성, 위임 능력 아님.
- **어드민의 타인 메모리 위임 접근** — 브로커 메모리는 주체 무관 항상 self(에스컬레이션 없음). 타인
  큐레이션은 memory_routes(053) 별도 경로.
- 벡터/하이브리드 discover, admin UI 정책 편집 — 브로커 공통 후속(백로그).
- **챗 직접 회상의 채널 모델** — `format_memory_hits`는 순수 포맷터일 뿐 격리 장치가 아니다(적대 리뷰
  104 P2, 미문서 경계로 명시). 브로커 위임 경로는 flow가 결과를 라벨 붙은 별도 Human 데이터 채널로
  감싸 격리하지만(learning 100), 챗 직접 회상은 회상 사실을 persona 프롬프트에 합친다(104 이전부터의
  설계). 자기 user_id 기억 = 자기 대화서 추출된 자기 사실이라 교차유저 인젝션은 아니나, 이 채널 결정을
  데이터 채널로 바꾸는 것은 별도 스펙. 이 스펙이 추가한 브로커 memory 경로는 flow 채널 격리 대상이다.

## codex 적대 리뷰(3판정)

- **[P2 실결함]** `limit` 타입 미검증 — 브로커는 `args.limit`를 무검증 전달해 `{"limit":"boom"}`이면
  `recall_probe`의 `[:limit]`에서 TypeError, `-1`이면 꼬리절단. → `recall_probe`에 정수 강제+범위 clamp
  `_clamp_limit`(엔드포인트 스키마 1-10과 동일 경계, 084가 이미 방어 슬라이스를 둔 지점). 세 입구를 같은
  경계로(교차입구 불변식은 공유 지점에, learning 103).
- **[P2 실결함]** 승인 재개 브로커 user_id 누락 — `_build_resume_broker`가 `user_id`를 받고도
  `PolicyScopedBroker`에 안 넘겨, 승인 재개 시 `MemoryProvider._user_id=None` → `memory:user`가 사라짐
  (누출 아님·fail-closed지만 자기 기억 접근이 재개서 깨지는 기능 회귀). → `user_id=user_id` 주입.
- **[P2 미문서 경계]** `format_memory_hits`는 격리 아님(위 비목표에 명시 + docstring 강화 + 브로커 경로는
  flow 채널 격리라는 안전 불변식은 H·U가 이미 커버).
- **오탐(기각)**: cap_id 변종(`memory:USER`·`memory:user/../x`·널바이트·접두사 중복) 승격 안 됨,
  `args.user_id` 타 스코프 지정 불가, 머신 principal 차단, 챗 2곳 포맷 drift 0 — 전부 공격 실패.
