# 124 — 조율형이 도구/문서/기억을 못 쓰던 버그: discover 어휘 필터 → 랭킹 전환

## 배경 / 왜

사용자 보고: **조율형(orchestrate) 에이전트가 도구·문서·기억 기능을 사용하지 못한다.**

### 근인 (실 broker로 결정적 재현)
`PolicyScopedBroker.discover(query)`는 `_permitted`(allowlist ∩ RBAC) 통과 후보에 **어휘 필터**를
건다:
```python
q = (query or "").strip().lower()
if q:
    caps = [c for c in caps if q in f"{c.name} {c.id} {c.hook}".lower()]
```
이 필터는 **"쿼리 전체 문자열이 능력 텍스트의 부분문자열일 때만" 남긴다**(방향이 뒤집힘 — query⊆cap).
자연어 쿼리("오늘 뭐 했지 기억나?")는 짧은 능력 이름/id/hook의 부분문자열이 절대 아니므로 **모든 능력이
탈락**한다. 재현:
| 쿼리 | memory:user | mcp:local-tools |
|---|---|---|
| `""`(빈) | 1개 | 3개(web_search/echo/delete_record) |
| `"오늘 뭐 했지 기억나?"` | **0** | **0** |

조율형 흐름은 `broker.discover(state["query"])`로 위임 대상을 찾으므로(orchestrate.py select 노드),
실제 쿼리에선 항상 빈 목록 → 위임 대상 0 → 도구·문서·기억 전부 못 씀. (에이전트 위임도 같은 이유로
쿼리가 우연히 이름을 포함할 때만 됐음.)

## 설계 (사용자 결정: 필터→랭킹 전환)

- `discover`의 **하드 어휘 필터를 랭킹으로 전환**: 허가된 후보를 버리지 않고 `limit`까지 반환하되,
  **쿼리 토큰과 겹치는 수가 많은 순**으로 정렬(0 겹침도 유지). 겹침 동수는 안정 정렬로 기존 순서 보존.
  ```python
  q = (query or "").strip().lower()
  if q:
      q_tokens = [t for t in q.split() if t]
      caps.sort(key=lambda c: sum(t in f"{c.name} {c.id} {c.hook}".lower() for t in q_tokens),
                reverse=True)
  return caps[:limit]
  ```
- **보안 불변식 불변**: `_permitted`(allowlist ∩ RBAC·deny-by-default·존재 비노출)는 그대로. 이번 변경은
  **허가된 후보를 과도하게 떨구던 후처리 필터만** 랭킹으로 바꾼다(허가 범위 확대 아님).
- "카탈로그 작아 벡터 없이 시작"(설계결정 10) 의도와 정합 — 작은 카탈로그는 랭킹+limit로 충분,
  하드 필터로 0을 만들 이유가 없었다.

## 검증

- **단위/통합(실 broker)**: allowlist=[memory:user]/[mcp:local-tools]로 discover를 (a) 빈 쿼리,
  (b) 실제 자연어 쿼리, (c) 이름 포함 쿼리로 호출 → **(b)에서도 능력 반환**, (c)는 겹치는 능력이 앞으로.
  RBAC 거부 능력은 여전히 안 뜸(게이트 무회귀).
- **무회귀**: 능력 브로커 기존 verify(101/103/104/105 등) 통과 — 특히 empty/exact 쿼리 동작·_permitted.
- **적대(codex)**: 랭킹 전환이 allowlist/RBAC 게이트를 우회하나·limit 경계·토큰 0겹침 유지·빈 쿼리 경로 등
  여집합.
- **브라우저(가능하면)**: 조율형에 작동 MCP(local-tools) 능력 부여 후 플레이그라운드서 실제 도구 호출까지.

## 비목표 (OUT)

- 시맨틱/벡터 검색 — 카탈로그 커지면 후속. 지금은 토큰 겹침 랭킹으로 충분.
- allowlist/RBAC 게이트 로직 변경 — 무관(보안 표면 불변).
- 조율형 select/LLM 선택 로직 변경 — discover가 후보를 주면 기존 select가 고름(무변경).
