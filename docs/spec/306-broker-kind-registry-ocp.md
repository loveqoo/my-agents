# 306 — 브로커 kind 파싱 OCP 흡수(레지스트리 구동)

## 배경
구조 리뷰(스펙 182/183, backlog:327)가 남긴 "중간 우선" 항목. 브로커 provider 라우팅은 레지스트리
(`_by_kind`)로 OCP를 지키는데, **cap_id 파싱 두 함수만 하드코딩 if-체인**이다:
- `common._kind_of(item)`: 접두사(`mcp:`/`rag:`/`memwrite:`/`memedit:`/`memory:`) if-체인 → kind, 그 외 agent.
- `common._cap_resource(cap_id, kind)`: kind별 if-체인으로 `_parse_*` 디스패치.

**함정(잠재 정합성 결함)**: 새 kind 추가 시 상수·`_kind_of` 분기·`_cap_resource` 분기·`_parse_*`를 각각
손봐야 한다. `_cap_resource` 분기를 빠뜨리면 per-cap RBAC 리소스(`capability:{kind}:{resource}`)가
**조용히 오추출**(fallthrough로 cap_id 전체 반환) → 인가 게이트 오동작(스펙 112 경계). 검사지점(파싱)과
부수효과(RBAC 판정)가 어긋난 틈(learning: installed-guard-isnt-covering-guard).

## 핵심 관찰(실측)
5개 kind의 **리소스 추출이 전부 균일**하다 — `{kind}:` 접두사 스트립:
- mcp `mcp:server/tool`→`server/tool`(body 전체)·rag `rag:coll`→`coll`·memory/memwrite/memedit
  `{k}:user`→`user`·agent bare `agt_…`→접두사 없어 원본. `_cap_resource`의 5분기 + `_parse_rag/_mem/
  _memwrite/_memedit`가 **모두 같은 한 규칙**이다(`_parse_mcp`만 2레벨 튜플이라 진짜 다름, 유지).

## 설계 — 단일 kind 레지스트리로 파생
provider마다 `resource_of()`를 두는 backlog 문안 대신 **단일 레지스트리 구동**을 택한다: 추출이 균일해
per-provider 메서드는 5중복(과추상, 구조 지시의 "YAGNI는 구조 잡히기 전까지"에 반함). `_kind_of`·
`_cap_resource`가 context-free(브로커 인스턴스 없이 a2a_server도 호출)라 provider 인스턴스에 못 매단다.

- **`_PREFIXED_KINDS` 레지스트리**(common.py, 상수 바로 뒤 단일 출처): 접두사 있는 kind 목록. agent는
  bare fallback이라 밖. **새 kind = 여기 한 줄만 등록** → 두 파서가 파생(OCP 봉인).
- **`_strip_kind(item, kind)`** 균일 프리미티브: `{kind}:` 스트립(없으면 원본). 리소스 추출 단일 규칙.
- **`_kind_of`**: `_PREFIXED_KINDS` 순회, 첫 매칭 접두사 kind 반환, 그 외 `CAP_KIND_AGENT`.
- **`_cap_resource`**: `return _strip_kind(cap_id, kind)`(if-체인 소거, 하드코딩 분기 0).
- **`_parse_rag/_mem/_memwrite/_memedit`**: `_strip_kind` 위임 **얇은 별칭으로 유지**(verify_104/105/111이
  단위 단언으로 쓰는 테스트된 계약 — 제거하면 테스트 깸, 별칭은 kind-격리 시맨틱 보존). `_parse_mcp` 불변.

## 행위 불변(핵심)
순수 리팩터 — **모든 cap_id에 대해 파싱 출력 바이트 동일**해야 한다(RBAC 리소스 문자열이 바뀌면
인가가 넓어지거나 좁아짐). 균일 규칙이 기존 if-체인과 동일함은 kind별로 실측 검증(아래). 유일 이론적
차이는 `agent:`로 시작하는 cap_id인데, agent cap은 bare `agt_…`뿐이라(`_kind_of`가 `agent:`를 agent로
분류하지 않음·코드가 `agent:` cap_id를 만들지 않음) 도달 불가 — 테스트+codex로 핀.

## 접두사 모호성
접두사는 콜론 종단이라 iteration 순서 무관(어느 kind 문자열도 다른 것+`:`의 접두사가 아님 — memory/
memwrite/memedit는 char 4서 분기). 미래 kind가 기존 것의 접두사면 문제될 수 있으나 현재 없음(테스트로 핀).

## 검증 (사다리 3런 — authz-인접이라 행위 불변이 핵심 불변식)
- **단위(신규 verify_306)**: 전 kind 라운드트립(`_kind_of(f"{k}:x")==k`·`_cap_resource(f"{k}:x",k)=="x"`·
  agent bare·빈 리소스·cross-kind 격리) + **드리프트 핀**(`set(_PREFIXED_KINDS)|{AGENT}` == 정의된 전
  CAP_KIND_* 집합 → 새 kind가 레지스트리 누락 시 실패). + 기존 if-체인 출력과 신규 출력 동치 표.
- **실인프라(기존 브로커 verifier)**: verify_066/100/101/103/104/105/111/112 전부 PASS(행위 불변).
- **게이트**: metrics-fast 0(ruff·mypy — `_kind_of` str 반환·타입 무붕괴).
- **적대(codex, read-only)**: "균일 `_cap_resource`/`_kind_of`가 기존 if-체인과 전 cap_id에 대해 동일
  출력인가? `agent:`-접두사·빈·mcp server/tool 엣지서 RBAC 리소스 드리프트로 인가 확대/축소 있나?"

## OUT
- provider 계약에 `matches`/`resource_of` 메서드 추가(균일이라 과추상). 미래 비균일 kind가 생기면 그때
  per-provider 오버라이드 도입(YAGNI 트리거).
- broker/ 파일 재분할(이미 패키지화됨)·`_parse_mcp` 변경(2레벨 튜플, 별개).
