# 코드 집중 리뷰 재료 — 복잡도 스냅샷 (2026-07-18, 스펙 383~391 구간 직후)

> 구남님 "코드 복잡도가 많이 올라가 있다" 인식의 수치화. 리뷰 포커스 제안 포함.

## 전체 건강(게이트 기준으로는 그린)

- 함수/블록 1,176개 · **평균 CC A(3.90)** · 분포: A 892 / B 223 / **C 61** (D+ 0 — 게이트 상한 C).
- MI 전 파일 A. metrics-fast 전판 그린.

## 체감 "복잡도 상승"의 실체 3축

### ① 이번 주(383~391) 집중 성장 지점 — A2A 캠페인
| 파일 | 변화 | 성격 |
|---|---|---|
| chat_stream.py | +260줄 | 388 서빙 확장(세션·기억·승인) — 헬퍼 7종 추출로 게이트는 지켰으나 모듈 책임이 커짐 |
| chat_trace.py | +175줄 | 386 트레이스 가족 이동(수용처) |
| a2a_server.py | +165줄 | 387/388 입구 확장 — **인가 경계라 리뷰 최우선** |
| chat_approval.py | +68줄 | resolve_and_resume 관문 신설 |

### ② 파일 비대(Tier 3 미착수분과 일치)
chat.py 1,262 · blocks.py 995 · batch/jobs.py 904 · chat_context.py 812 · runtime.py 738 · seed.py 715.

### ③ 경계선 지표
- MI 문턱(20) 근접: **blocks.py 21.6** · chat_context.py 23.9 · chat.py 24.9 — 다음 추가가 문턱을 깬다.
- C-급(11~20) 상위: artifact.ProduceContext.form 19 · parse_entity_lines 18 · _probe 18 ·
  _pick_tool_call 18 · _resolve_mcp_servers 18 · build_mcp_tools 17 · sync_code_nodes 17 ·
  _graph_fingerprint 17 · … (전체 61개 목록은 `uvx radon cc -s -n C packages/`).

## 리뷰 포커스 제안(우선순위)

1. **a2a_server + chat_approval + chat_stream** — 이번 주 성장분이자 인가/승인 경계.
   codex 스팟 리뷰는 통과했으나 "게이트 사슬 대응"(회고 393) 관점의 인간 리뷰가 유효.
2. **blocks.py(995줄·MI 21.6)** — 문턱에 가장 가까움. 프롬프트/MCP/기억 CRUD가 한 파일 —
   Tier 3식 분할 후보 1순위.
3. **C-상위 18 함수** — 게이트 안이지만 15~19는 다음 수정에서 D로 넘어갈 예비군.
4. 참고: 캠페인 374 Tier 3(chat.py ChatTurnService·jobs plan/execute) 백로그 항목이 이 리뷰의
   자연스러운 후속.
