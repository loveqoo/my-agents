# 093 — 연결된 에이전트가 있으면 MCP 서버·RAG 컬렉션 삭제 차단 (제안 #5)

> 상태: 초안(AI 작성, 인간 검토 대기). 제안 8항목 중 #5.
> 참고 자산: spec 046 + retrospect 035(재료 정리·cascade·dangling·dry-run), retrospect 036(047
> 회고 — 셀프 GREEN 뒤 **삭제가드 누락** 적발), learning 050(delete 가드는 형제 연산 안 덮음·
> operation-symmetry), learning 048(생성시점 보장≠수명 전체), learning 069/070(모든 입구·전 수명
> 커버·covering-guard), spec 062(중앙 error detail 헬퍼).

## 1. 배경 / 문제

MCP 서버와 RAG 컬렉션은 에이전트 config에서 **name 문자열**로 참조된다(FK 아님):

- `AgentConfig.mcps: list[str]` → `McpServer.name` (런타임 해석: `chat.py:207` `McpServer.name.in_(mcps)`)
- `AgentConfig.vectorTables: list[str]` → `Collection.name` (런타임 해석: `chat.py:233` `Collection.name.in_(vt_names)`)

현재 두 삭제 엔드포인트는 **참조 무검사로 즉시 삭제**한다:

- `DELETE /blocks/mcp-servers/{id}` (`blocks.py:313`) — id로 McpServer 로드 후 그대로 delete.
- `DELETE /rag/{cid}` (`rag.py:152`) — id로 Collection 로드 후 문서·청크 CASCADE 삭제.

삭제하면 에이전트 config에는 **dangling name**만 남고, 런타임이 그 이름을 못 풀어(name.in_ 미스)
**조용히 도구/RAG 없이 동작**한다(로그 warning만: `chat.py:259` "vectorTables 미해석"). 관리자는
자기가 방금 살아있는 에이전트의 능력을 깼다는 걸 알 방법이 없다. 참조 무결성을 삭제 시점에 세워 이
실수를 막는다.

## 2. 설계 결정

### 2.1 무엇이 "연결됨"인가 — 참조 스캔 범위 (**핵심 결정, codex 적대리뷰로 교정**)

두 소스의 **합집합**을 참조로 본다:

1. **런타임 유효 — `Agent.config`** (1차): 코드 측정으로 `Agent.config`는 **활성(발행) 버전 config**다.
   `update_agent`는 draft 버전만 갱신하고 `Agent.config`는 안 건드리며(`agents.py:169` "서빙 config/
   active_version 은 건드리지 않음"), `activate_version`이 활성화 시 `agent.config = cfg`로 덮어쓴다
   (`agents.py:235`). 런타임(`chat.py:99·306`)은 이 `Agent.config`를 로드. 여기 name이 있으면 *지금
   서빙 중*인 에이전트가 삭제로 깨진다. → `where=active`.
2. **잠복 참조 — 모든 버전(archived 포함)** (2차): `AgentVersion`의 config가 참조. → `where=version`.
   **draft 참조는 실재하는 divergent 상태**다 — 관리자가 MCP "foo"를 추가해 draft 저장(활성화 전)하면
   `Agent.config`엔 없고 draft엔 있다. 지금 "foo"를 지우면 그 draft를 **활성화하는 순간 dead ref**가
   된다(learning 048 "한 시점 보장≠수명 전체").
   - **archived도 포함(초안의 "archived 제외"를 codex가 반증 → 교정).** 초안은 "archived는 draft를
     거치지 않으면 활성화 불가"로 잘못 가정해 제외했으나, **측정 결과 틀렸다**: `activate_version`은
     archived 롤백을 **명시적으로 허용**한다(`agents.py:225` 주석 "archived=롤백은 허용", `:232`
     active 승격 → `:235` `agent.config` 부활). 즉 archived 참조는 *죽은 이력이 아니라 롤백 가능한 live
     참조*다 — 지우면 롤백 순간 서빙 config에 dead ref가 부활한다. **활성화 가능한 버전이면 어떤
     상태든 live 참조**이므로 전 버전을 스캔한다(learning 069/070 covering-guard의 정확한 사례:
     "archived는 dead"라는 미검증 가정이 곧 맹점이었다).

근거: learning 069/070(같은 자원의 *모든 입구*·전 수명에 걸쳐 판정), learning 048(생성 한 시점에 건
보장은 수명 전체를 못 덮음), retrospect 036(셀프 GREEN 뒤 가드 누락 — 이번엔 codex가 그 자리에서 적발).

> **UX 정합 주의(측정으로 드러난 함정):** 블록 관리 UI의 "usedBy" 배지는 `blocks.py:_count_by`가
> **`Agent.config`만** 세므로 *활성* 참조만 보여준다. 합집합으로 차단하면 "usedBy 0인데 삭제가 막힘"
> 모순이 생길 수 있다 → **409 메시지가 참조 위치(활성/버전)와 에이전트명을 구분해** 실어, "에이전트
> X의 *버전*이 이걸 참조합니다"로 정직하게 설명한다(§2.4). union의 안전성과 UX 정합을 둘 다 만족.

### 2.2 참조 키 = name (id 아님)

삭제 요청은 **id(uuid)**로 온다. 먼저 McpServer/Collection을 **name으로 resolve**한 뒤 그 name으로
config를 스캔한다. `McpServer.name`·`Collection.name`은 **unique**(`models.py:35·65`)라 name↔행이
1:1 — 참조 스캔에 모호성 없음.

### 2.3 입구 열거 — 닫힌 집합 (learning 050 operation-symmetry)

**name 링크를 끊는 입구는 삭제만이 아니다** — codex 적대리뷰가 rename을 형제 입구로 적발. 참조 name을
깨는 모든 입구에 **동일 헬퍼**를 건다:

- **MCP 서버 삭제**: `DELETE /blocks/mcp-servers/{id}` **단 하나**. 일괄/cascade/seed 개별삭제 경로
  없음(전수 grep — seed는 empty일 때 *생성*만).
- **컬렉션 삭제**: `DELETE /rag/{cid}` **단 하나**. (`rag.py:352` 문서삭제는 하위 Document — 무관.)
- **MCP 서버 rename**: `PUT /blocks/mcp-servers/{id}` — name 변경 시 옛 name이 config에 dangling으로
  남는다(런타임 `McpServer.name.in_(["old"])` 미스 → 도구 조용히 소멸). **name이 바뀌고 옛 name이
  참조되면 409**(값은 옛 name 기준, `action="이름 변경"`). Collection은 `update_collection`이 name을
  수정하지 않아(embedding/dims만 불변 유지, name 변경 API 없음) 대칭 입구 없음.
- → 세 입구 모두 `agents_referencing`(단일 파라미터화 헬퍼) 공유(드리프트 0). rename은 삭제와 같은
  포매터를 `action` 인자만 바꿔 재사용.

### 2.4 차단 동작

- 참조하는 에이전트가 **≥1이면 `409 Conflict`**, `detail`에 **사람이 읽는 문자열**로 막는 참조
  목록을 실어 반환한다(**dict 아님 — 측정으로 교정**). 각 참조는 `이름(활성|버전)`으로 위치를 문자열
  안에 보존 — usedBy 배지(활성만)와 어긋나는 버전 차단을 정직히 설명. 조용한 무시·자동 강제삭제
  **금지**. 예:
  `이 MCP 서버을(를) 1개 에이전트가 사용 중이라 삭제할 수 없습니다: Weather Bot(활성). 먼저 각 에이전트에서 해제한 뒤 삭제하세요.`
  포매터 `references.referenced_message(refs, 자원명, action)`이 blocks·rag 공유(drift-0).
- **메시지 길이 상한(codex P2):** 참조가 수백이면 나열이 무한정 길어지므로 **처음 20개 + "외 M개"**로
  축약(총 개수는 실제값 유지). 프런트는 `httpError`가 600자 상한으로 추가 방어.
- **왜 dict가 아니라 string인가(핵심 교정):** 중앙 error 헬퍼 `httpError.ts`(spec 062)와 이 뷰들의
  기존 409 관례(`CollectionsView.tsx`: "409 = … 서버 메시지를 그대로 노출")는 **string `detail`만**
  추출·노출한다. dict를 주면 프런트가 일반 폴백(`METHOD path → status`)만 보여 참조 목록이 안 뜬다.
  → 백엔드가 사람이 읽는 문자열을 반환하는 게 이 코드베이스의 확립된 관례이며, **프런트 변경 0줄**로
  기존 `message.error(e.message)` 경로가 그대로 안내를 렌더한다.
- **force 옵션 없음(초안)**: 안전 기본은 차단. detach 후 재시도가 정상 경로. (원하면 후속 스펙에서
  `?force=true` + 각 에이전트 config에서 자동 detach를 논의.)
- 프런트(`CollectionsView`, `BlocksView` MCP 삭제): **변경 없음**. 두 삭제 핸들러는 이미
  `catch (e) { message.error(e instanceof Error ? e.message : …) }`로 서버 메시지를 그대로
  노출한다(spec 062 `httpError`가 string `detail`을 Error.message로 전달).

### 2.5 RBAC/소유권 체크리스트 — **미적용**

객관 신호로 판정(자가판정 금지, `docs/spec/CLAUDE.md`): 두 삭제 엔드포인트에 `user_id`·owner
스코핑·`_own_scope`/`_visible_or_404`/`_assert_*owns` **없음**. MCP 서버·컬렉션·에이전트는 전역
**admin 카탈로그**로 테넌트별 데이터가 아니다. → 트리거 조건 불충족, 체크리스트 미적용.

## 3. 구현

### 3.1 참조 스캔 헬퍼 (단일 소스)

`agents.py`(또는 공유 모듈)에 파라미터화 헬퍼:

```python
async def agents_referencing(session, field: str, name: str) -> list[dict]:
    """config[field]에 name을 담은 참조 목록 [{"agent": name, "where": "active"|"version"}].
    field ∈ {'mcps','vectorTables'}. Agent.config(활성 서빙) → where=active,
    모든 AgentVersion.config(archived 포함, 롤백 가능=live) → where=version.
    같은 에이전트가 양쪽이면 active 우선 1건(dedupe)."""
```

- 초안은 **파이썬 스캔**(에이전트 수 소규모 admin 카탈로그, 기존 `_count_by`와 동형): 전 에이전트를
  `selectinload(Agent.versions)`로 로드 → `Agent.config[field]`에 name 있으면 active, 없고 **아무
  버전(archived 포함)** config에 있으면 version. 존재하는 `_count_by` 로직을 이 스캐너와 `config_names`
  normalizer로 승격(둘 다 name-in-list, drift 0).
- (성능 필요 시 JSONB containment 쿼리 `config[field] @> to_jsonb([name])`로 후속 최적화 — 초안은
  단순·정확 우선. name은 unique라 부분매칭 위험만 codex로 확인.)
- 얇은 래퍼는 호출측이 field 고정(`"mcps"` / `"vectorTables"`) — 파생, 저장 안 함.

### 3.2 삭제·rename 입구에 가드 (+ 가드/런타임 normalizer 단일화)

```python
# 삭제(blocks.delete_mcp_server / rag.delete_collection)
refs = await agents_referencing(session, "mcps", obj.name)   # 컬렉션이면 "vectorTables", c.name
if refs:
    raise HTTPException(status_code=409, detail=referenced_message(refs, "MCP 서버"))

# rename(blocks.update_mcp_server) — name 바뀔 때만, 옛 name 기준
if new_name is not None and new_name != obj.name:
    refs = await agents_referencing(session, "mcps", obj.name)
    if refs:
        raise HTTPException(status_code=409,
            detail=referenced_message(refs, "MCP 서버", action="이름 변경"))
```

- **가드/런타임 단일 normalizer(codex P2):** `_config_has`와 `chat.py`가 `references.config_names`를
  공유한다 — `config[field]`가 list[str] 아닌 모양(dict/스칼라/None, 비-str 원소)이면 **양쪽 모두**
  참조 아님으로 접는다. 예전엔 런타임이 dict를 키로 해석(`name.in_(dict)`)하고 가드는 무시해 판정이
  어긋났다. 이제 동일 함수로 drift 0.

### 3.3 프런트 409 처리 — **변경 없음**

- 백엔드 `detail`이 **string**이라 기존 `httpError`(spec 062, string detail만 노출)가 그대로
  `Error.message`로 전달하고, `CollectionsView`·`BlocksView`의 기존 `message.error(e.message)`가 안내를
  렌더한다. 프런트 코드 추가 0줄(dict였다면 커스텀 파싱 필요했음 — string 선택의 이유, §2.4).

## 4. 완료 조건 (측정가능) — verify_093 GREEN(40/0)

- [x] **단위**: (a) `config_names` normalizer(list만 인정·dict/스칼라/비-str 접음), (b) `_config_has`
      정확 멤버십, (c) `referenced_message` string·where 라벨·action·길이상한("외 M개").
- [x] **통합(실DB)**: MCP/컬렉션 활성 참조 → 409(T1·T5), 비-서빙 버전 참조 → 409 where=version(T2),
      **archived 참조 → 409**(T3, 롤백 가능=live), 미참조 → 삭제 성공(T4·T6), 참조 해제 후 삭제 성공(T7),
      **참조중 rename → 409**(T8), name 동일 update는 허용(T9, 과잉차단 아님).
- [x] **적대(codex, rung③)**: 5건 적발 → P1 archived부활·P1 rename·P2 타입불일치·P2 길이 **수정**;
      P1 TOCTOU는 §5로 이연(서빙 불변식 논증). name unique·부분매칭 없음 확인됨.
- [ ] **브라우저(보조)**: 프런트 변경 0줄이라 저가치 — 렌더 경로는 `httpError` 독해로 확인(string
      detail → `e.message` → `message.error`). 서버 가동 시 한 컷만 보조 확인.

## 5. 비목표 / 알려진 잔존(silent partial guard 금지 — 명시 기록)

- force/자동 detach(후속 후보).
- **참조 name rename 시 config 자동 rewrite(rename propagation)**: 이번엔 참조중 rename을 **차단**만
  한다(§2.3). 옛 name을 새 name으로 config에 전파하는 건 별개 문제로 남긴다.
- 이미 존재하는 dangling 참조의 소급 정리(spec 046 계열, 별개).
- **[잔존 — codex P1 TOCTOU, 후속 spec 094 후보]** 가드 스캔과 삭제 commit 사이, 또는 삭제와 동시에
  `update_agent`(draft) / `activate_version`이 그 name을 config에 넣는 경쟁. **서빙 불변식은 이미
  보전됨**: (a) `update_agent`는 draft만 쓰므로 경쟁이 남겨도 *비-서빙* draft의 dangling일 뿐 런타임
  영향 없음, (b) 그 draft를 활성화하려면 `activate_version`을 거치는데 — 이 스펙은 아직 활성화 입구에
  검증을 걸지 **않는다**(그래서 삭제→활성화 순번이면 서빙 dead ref 가능). **완전 차단은 config 쓰기
  경로(update_agent/activate_version)에도 참조 존재검증 + 삭제와의 직렬화(advisory lock)가 필요** →
  단일-admin 카탈로그엔 과한 동시성 장치라 **spec 094로 분리**. 여기선 "삭제/rename 시점 스냅샷 차단"이
  경계임을 정직히 기록(retrospect 036 교훈: 부분 가드를 조용히 출하하지 말고 잔존을 호명).
