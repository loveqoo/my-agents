# 106 — config 필드 왕복 완전성 = 4지점 교집합 / 좋은 ID 네임스페이스는 저작 UI를 순수 포매팅으로 만든다

## 맥락

능력 브로커(100–105)를 UI에서 엮으려 편집 폼에 `impl`·`capabilities` 두 필드를 노출(스펙 106).
백엔드 무변경 목표였으나 직렬화에 구멍 하나, 그리고 저작 UI가 뜻밖에 싸게 끝난 이유 하나.

## 배운 것

### 1. config 필드의 왕복 완전성은 *4지점의 교집합*이다 — 하나만 빠져도 말없이 샌다

에이전트 config에 새 필드를 더해 폼이 편집하게 하려면 **네 지점 전부** 있어야 왕복이 닫힌다:

1. **쓰기 스키마**(`AgentCreate`/config-in) — 저장 요청이 그 필드를 수용.
2. **읽기 직렬화**(`AgentOut` 스키마 + `agent_to_out`) — 조회 응답이 그 필드를 *방출*.
3. **폼 초기화**(`configOf`/`initial`) — 조회한 값을 폼 상태로 로드.
4. **폼 저장**(`save`) — 폼 상태를 config로 조립.

스펙 106에서 `capabilities`는 (1)만 있었다(101이 write-schema에 추가). 직렬화는 `impl`은 방출했지만
`capabilities`는 **말없이 빠져** 있었다. 그러면 폼이 저장은 성공하나(1·4 OK) **편집 재열기 때
사라진다**(2 누락 → 조회 응답에 없음 → 3이 빈값 로드). happy-path(방금 저장)엔 안 보이고,
*재열기*라는 다른 흐름에서만 터진다.

→ **처방**: config 필드를 폼에 노출할 땐 필드명을 **schema + serializer + form 파일에 grep**해
네 지점을 닫힌 집합으로 확인한다. "쓰기 되니 됐다"는 절반. 특히 직렬화는 **비대칭 누락**(형제 필드
`impl`은 있는데 새 필드만 빠짐)이 눈에 안 띈다 — 형제 필드 옆줄에 나란히 두고 대조.

이건 learning 104 "새 상태축을 배선하면 그 객체 만드는 *모든* 팩토리를 세라"의 **config-필드판**이다.
104는 생성자 인자(build/resume 팩토리), 106은 config 필드(write/read/form 3파일) — 같은 형태:
*한 곳을 고친 것이 모든 곳을 고친 것은 아니다*, 닫힌 집합으로 세라.

### 2. 좋은 ID 네임스페이스는 저작 UI를 *순수 포매팅 계층*으로 만든다

능력 피커는 **새 백엔드 카탈로그 엔드포인트가 필요 없었다.** cap id가 `<kind>:<name>` 규약(100–105)이라
폼이 이미 로드하는 목록에서 문자열 포매팅으로 조립됐다:
- `memory:user`·`memwrite:user` — 고정 2개
- `rag:<collection.name>` — 이미 로드한 collections
- `mcp:<server.name>` — 이미 로드한 mcp blocks
- `agt_<agent_id>` — 이미 로드한 agents(원격만)

브로커 설계 때 "이름에 대상 안 박고 규약으로 kind를 표현"한 결정(103·104)이 **저작 계층에서 배당**을
냈다: 강제(백엔드 broker)·표시(UI 피커)가 같은 ID 문법을 공유하니 UI는 목록을 *포맷*만 하면 된다.

→ **처방**: 능력/권한/리소스를 식별할 땐 `<kind>:<name>` 같은 **파생 가능한 규약**을 택하라. 그러면
관리 UI가 그 목록을 새로 조회하는 대신 이미 가진 데이터에서 조립할 수 있어 백엔드 표면이 안 는다.
반대로 불투명 opaque id면 저작 UI마다 전용 카탈로그 엔드포인트가 필요해진다.

## 부수 함정

- **`/agents/{uuid}` 경로 충돌**: 목록성 엔드포인트(`/agent-impls`)를 `/agents` prefix 라우터에 두면
  `{agent_id}`(uuid)로 파싱돼 422. top-level 별도 라우터로 분리.
- **vite IPv6-only 바인딩**: 브라우저 검증은 `127.0.0.1`이 아니라 `localhost`(=`::1`)로 접속.
- **antd 라벨 Tag 중첩** → `getByText(exact)` 실패, 정규식 부분매칭.

## 적용

per-user/config 필드를 폼에 노출하는 모든 작업: (1) 필드 왕복은 write-schema∩serializer∩form 4지점
grep으로 닫고, (2) 리소스 식별은 파생 규약을 써 저작 UI를 포매팅 계층으로 유지한다.
관련: [[104-per-user-capability-bind-to-principal-not-cap-id]](네임스페이스·새 축 배선), [[index-layer-for-context-recall]].
