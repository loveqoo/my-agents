# 능력 브로커(Capability Broker) 설계 노트 — 스펙 前 스크래치

> AI 영역 스크래치. **아직 스펙 아님**(Planning 승인 전). 2026-07-01 티타임→실전 논의에서 맥락
> 살아있을 때 박아둔 설계 결정. Planning 진입 시 여기서 꺼내 `docs/spec/NNN-...`로 초안화.
> 백로그: `.dev/backlog.md` "discovery 기반 능력 오케스트레이션". 관련: spec 085(CustomAgent·ctx 주입
> 단일소스·실 노드 트레이스)·089(conformance)·026/042/057/061(A2A 등록·호출·단일화·노출)·064(Host
> poisoning fail-closed)·`net_guard`·[[index-layer-for-context-recall]]·[[agent-source-three-way-a2a-external]](오래됨—확인 필요).

## 문제 / 방향

전부 컨텍스트에 preload(에이전트·MCP·memory·RAG 목록)하면 (1) 매 턴 토큰 선형 증가, (2) 툴 스키마
비대→**모델 선택 잠김**(작은/싼 모델 무너짐, 프로바이더 툴 한도 상이). 대신 **discovery**로: 값싼
발견→필요시 상세→호출. 트레이드오프 비대칭(비싼 컨텍스트·모델락 ↔ 싸지는 턴)이라 discovery가 옳음.
선례: 이 하네스의 ToolSearch/deferred tools가 바로 이 방식. 우리 `INDEX.md`(후크 먼저·full은 불충분시)도 같은 패턴.

**핵심 통찰(099식):** A2A 오케스트레이션·MCP·RAG·memory는 4개 기능이 아니라 **1개 시임** —
`search/list(query)→후보` + `describe(id)→스키마/사용법` + `invoke(id,args)→결과`. 외부 에이전트도
"능력 제공자의 한 종류"일 뿐. 일회성 A2A 대신 능력 브로커 하나 짓고 넷을 다 꽂는다.

## 현재 상태 정정 (코드 확인, 2026-07-01)

이미 구현됨(내가 앞서 "미구현"이라 한 건 오독): 외부 A2A 카드 등록(026)·실호출 JSON-RPC(042,
`a2a_client.py`)·원격 A2A 단일화(057)·로컬 ui를 A2A로 노출(061, `a2a_server.py`)·SSRF/Host-poisoning
방어(064, `net_guard.py`). **진짜 갭은 하나**: external은 지금 `chat.py:58`에서 `is_remote_source`→
`_a2a_stream`(`chat.py:459`) **통째 프록시**뿐(트레이스 `a2a_call` 단일 노드). "로컬 플로우의 한
노드로 외부를 호출해 다른 노드와 조합"(오케스트레이션/서브스텝)이 없음.

## 설계 결정 10개

아키텍처 사실: 에이전트 그래프는 `packages/agent` 정의, **실행은 API가 호스팅**(`chat.py`가 runtime
import→build_agent→astream). ctx는 agent 자료구조지만 채우는 건 api. a2a_client·net_guard·casbin·
memory는 api쪽. → "계약=agent, 배선·정책=api"가 뼈대.

1. **배치**: 브로커 *인터페이스*=`packages/agent`(노드가 호출), *구현+정책*=`packages/api`. 에이전트는
   **이미 스코프된 브로커**를 ctx로 받음(085 U2 "ctx만 읽음" 보존). [지금 결정]
2. **노출**: 둘 다·브로커 하나 — (a) `ctx.tools`에 메타툴으로 *모델 주도* 발견, (b) ctx 순수 callable로
   *저작자 주도*(코드 flow 노드 결정적 호출). 099: 알면 코드, 정해야 하면 툴. [지금 결정]
3. **능력 서술자(공통)**: `{id, kind(agent|mcp|rag|memory), name, hook(한줄), input_schema(describe시),
   trust_tag}`. kind 판별자. MCP는 2단(서버→툴) 같은 검색 뒤. **한 줄 hook=INDEX 후크 판박이,
   load-bearing**(나쁜 설명=엉뚱 선택). [지금 결정 — 시임 심장]
4. **정책**: 에이전트 config allowlist **∩** 유저 RBAC(casbin 기존), **deny-by-default**, ctx-빌드 경계서
   강제, **발견·호출 둘 다** 게이트(발견 안 막으면 능력 존재 누설). [지금 결정 — deny-by-default 중요]
5. **출력 신뢰**: invoke 결과=*지시 아닌 데이터*, untrusted 태그, 별도 슬롯. 표준 툴출력 불신. 통째
   프록시(현재)는 결과가 로직 재유입 안 해 무위험; 서브스텝은 재유입→프롬프트 인젝션 표면 신설. [원칙 지금·태깅 세부 스펙때]
6. **네트워크 신뢰**: A2A·MCP 둘 다 `net_guard`/SSRF allowlist 재사용(MCP=새 외부 표면 같은 처방). [재사용]
7. **관측성**: `broker.invoke`가 트레이스 프레임 emit(오늘 `a2a_call` 노드처럼)→실 노드 타임라인 경계
   너머서도 정직(invisible 금지). [지금 결정]
8. **턴 예산**: 발견 왕복 상한(턴/대화당)+초과시 정직 표면화(silent 절단 금지). [원칙 지금·숫자 스펙때]
9. **마이그레이션/하이브리드**: ctx eager 집합(핫 소수) 유지 + 브로커 핸들(롱테일) 추가. `ctx.tools`
   안 뜯음·하위호환. 하네스도 하이브리드. [지금 결정]
10. **검색 메커니즘 = 하이브리드**: 일치/키워드(lexical) + 벡터(semantic)를 **정책 스코프된 집합
    위에서** 둘 다. 서로 다른 질문형: lexical=이름/식별자/kind 정확매치(고정밀·환각 없음), vector=
    이름 모르고 의도만 알 때. 두 후보목록→병합 재랭킹(RRF/가중합, 세부는 스펙때). pgvector 한
    인덱스(RAG 인프라 재사용)·**등록 시점 임베딩**·정책필터+벡터정렬을 한 쿼리에(`WHERE 허용 ...
    ORDER BY embedding`). 카탈로그 작으면 나열/lexical만으로 시작(벡터는 규모때 값). [지금 결정 —
    병합식·임계값 세부는 스펙때] 

## 열어둔 긴장

- **kind별 서술자 수렴?** 발견/기술은 통일 가능하나 **invoke 반환 모양은 kind별 상이**(MCP 스키마툴·
  A2A 자유대화·RAG 청크·memory 사실). 완전 통일 시도는 과적합. → 발견·기술 통일, **invoke 반환은
  kind별 두되 "텍스트로 접힌 공통 표현"**(트레이스·다음 노드 입력용) 제공. 스펙때 실제 2 kind로 측정(085식).
- 메모리 `agent-source-three-way-a2a-external`가 "미착수"로 남아 있는데 026에서 external 분기 이미
  들어감 → **오래된 기록 가능성**. 확인 후 정정(추측 금지).

## 완료조건 설계 힌트(스펙 진입 시)

측정가능하게: 데모 flow가 "로컬 노드→능력 발견→외부 A2A(또는 mock MCP) invoke→로컬 종합" 실 노드
타임라인을 내고, allowlist 밖 능력은 발견 단계서 안 보이며(deny-by-default 실증), 외부 출력이
untrusted 슬롯에 착지(인젝션 방어 실증). 099처럼 데모 1종이 스펙 자체 실증.
