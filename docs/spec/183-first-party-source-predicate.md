# 183 — Agent.source 제1자/제3자 축 술어(OCP 완성)

## 배경(스펙 182 리뷰 발견)
`Agent.source`의 **remote/local 축**은 `is_remote_source(source)` 단일 술어로 잘 통일됐다
(`code|external`=원격). 그러나 자매 축인 **제1자(ui/code, 우리가 저작·제어) vs 제3자(external, 밖에서
가져옴)** 는 술어가 없어, 리터럴 `source in ("ui","code")`·`== "external"`·`!= "external"`가 여러 곳에
흩어졌다. 새 source 추가 시 각 게이트를 개별 감사해야 하는 shotgun surgery이며, **보안 게이트**(A2A
노출·재공개 차단)가 이 리터럴에 걸려 한 곳을 빠뜨리면 조용히 오동작한다. → 이미 검증된 `is_remote_source`
패턴을 이 축에도 그대로 적용해 OCP를 완성한다.

## 설계
`packages/agent/src/agent/runtime.py`에 `is_remote_source` 옆에 자매 술어 2개:
- `is_first_party(source)` = `source in ("ui","code")` — 로컬 페르소나·설정 有, A2A 노출/페르소나 갱신 대상.
- `is_third_party(source)` = `not is_first_party` — 밖에서 가져온 것(오늘은 external), 재공개 금지·사용 항상 허용.

**Agent.source 축 한정** — McpServer.source는 어휘가 다르므로(`local|custom|external`) 이 술어 대상 아님.

### 치환(의미 보존 — 오늘 source⊆{ui,code,external}이라 세 리터럴 형태가 동치)
| 사이트 | 기존 | 치환 | 축 |
|---|---|---|---|
| a2a_server.py:41 노출 게이트 | `not in ("ui","code")` | `not is_first_party` | 제1자 |
| a2a_server.py:248 실행 라우팅 | `== "code"` | `is_remote_source` | **remote**(자매 축 재사용) |
| agents.py:434 페르소나 갱신 | `not in ("ui","code")` | `not is_first_party` | 제1자 |
| agents.py:504 재공개 차단 | `== "external"` | `is_third_party` | 제3자 |
| ownership.py:137 may_use_agent | `== "external"` | `is_third_party` | 제3자 |
| serializers.py:83 personaStale | `in ("ui","code")` | `is_first_party` | 제1자 |
| blocks.py:131 페르소나 참조 필터 | `in ("ui","code")` | `is_first_party` | 제1자 |
| blocks.py:157 페르소나 반영 | `in ("ui","code")` | `is_first_party` | 제1자 |

**제외**: chat.py:274 `r.source != "external"`는 **McpServer.source**(다른 어휘) — 손대지 않음.

## RBAC 경계(보안 게이트 포함 — 체크리스트)
- 순수 **리팩터(의미 보존)** — 인가/노출 경계 완화·강화 아님. a2a_server:41·agents:504는 보안 게이트라
  **동치 치환을 회귀로 핀**한다(오늘 3-source에서 리터럴==술어 동치, 단위+기존 게이트 테스트).
- 미래 4번째 source 도입 시 **의미가 갈리는 지점**(제1자/제3자 판정)이 이제 술어 한 곳 → 그때 한 번만 결정.

## 검증(완료 조건)
- **단위**: `is_first_party`/`is_third_party` 진리표(ui·code→first, external→third, 여집합 관계).
- **회귀(기존 게이트 무회귀)**: a2a 노출/재공개·may_use_agent·personaStale 관련 기존 verify 통과.
- **import 무오류** + pyflakes 0(신규 미사용 없음).

## 단계
- 술어 추가 → 7사이트 치환 + 라우팅 1사이트(is_remote_source) → 단위+회귀.

## 실행 결과
- **완료**: 술어 2개 추가(runtime.py), Agent.source 리터럴 7곳 치환 + a2a 라우팅 1곳(is_remote_source
  재사용). chat.py:274는 **McpServer.source(local/custom/external, 다른 어휘)** 라 제외 — 사이트별로
  읽어 오분류를 걸렀다(에이전트가 8곳으로 셌으나 1곳은 다른 축).
- **검증**: 술어 진리표 단위(verify_112)·verify_147 가시성 16/16·verify_161 personaStale·verify_154
  릴레이 12/0·verify_112 통과·import OK·pyflakes 무증가.
- **행동 보존 확증**: `is_third_party`≡`== "external"`(오늘 3-source에서 진리값 동일)라 무회귀. 변경을
  stash하고 재실행해 아래 사전 실패가 **내 변경과 무관**함을 증명.
- **발견(사전 존재 실패 — 이 스펙 범위 밖, 백로그)**: (1) `verify_152_no_reexport` V4 "code→400"이
  **stale**(스펙 154가 code 노출 허용으로 바꿨는데 테스트 미갱신). (2) `verify_083_expose_gate` 5건
  404(라이브 인프라/시드 의존). 둘 다 stash로 pre-183에서도 동일 실패 확인.
