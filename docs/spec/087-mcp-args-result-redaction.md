# 087 — MCP 호출 인자·결과 redaction (형제 trace 표면)

> 스펙 086 codex 적대 리뷰 F1의 분리 항목. **scope=최소(B)** — 사용자 합의(2026-06-30).
> 관련: learning 089(값 allowlist·형제 표면)·059(raw에서 캡)·065(중앙 경계서 처리), retrospect 070 §3.

## 배경 — 위협 모델 실측(과대평가 교정)

086 적대 리뷰가 "MCP args/result가 trace에 원문 노출 → 비밀 누출 **P0**"로 F1을 짚었다.
한 겹 더 파보니 그 프레이밍은 과장이었다:

- **시스템 자기 비밀은 이 표면에 안 온다.** MCP 서버 Bearer 토큰은 연결 *헤더*(`runtime.py`
  `headers["Authorization"]`)에 있지 도구 인자(kwargs)에 없고, 모델 api_key는 ChatOpenAI 설정이지
  도구 인자가 아니다. → `api_key`·`token`이 args/result로 새는 *실재* 경로는 없다.
- **표면은 인증된 admin/owner 전용**(spec 011/031/053). 공개 누출이 아니라 이미 인증된 관리자가
  *자기 세션 trace*를 보는 것. → codex의 "P0 누출"은 실은 **defense-in-depth 갭**.

그래서 086급 recursive value-allowlist는 보조도구(인스펙터)에 **과한 금칠**(메모리 원칙:
model/config·memory가 토대, 나머지는 과투자 금지). 대신 **싸고 정직한 최소 처방**으로 닫는다.

## 무엇을 한다 (scope B)

### 누출 표면(producer 1곳, 끝단 3곳)

원천은 모두 `runtime.py`의 calls_sink/interrupt이고, 끝단 3개가 같은 raw를 소비한다:

| producer | sink | 끝단 |
|---|---|---|
| `_execute` `args=kwargs`,`result=text` | `calls_sink` | Inspector `McpCall`(args+result), pending_trace |
| `interrupt(...)` `args=kwargs` | `Approval.args`(**DB 영속**) | ApprovalsView `JSON.stringify(item.args)` |
| `build_rag_tool` `_record` `args={query,top_k}` | `calls_sink` | Inspector `RagCall` (저위험) |

수리는 **원천 한 곳(runtime.py)** 에서 — sink 진입 *전에* redact(learning 065 중앙 경계, 끝단 N개 말고).
프런트는 변경 0(이미 redacted 데이터를 받는다).

### 두 처방

1. **민감-키 blocklist redactor (`_redact_args`)** — 재귀로 dict/list를 걷되:
   - 키가 `_SENSITIVE_KEY`(086 재사용: api_key·secret·token·password·auth·credential·bearer)면 값을
     `«redacted»`로. **평범한 키의 값은 원문 보존**(인스펙터 디버깅 가치 유지 — args는 사람에게 보일
     표면이라 086 노드델타와 polarity가 정당하게 다름).
   - 문자열 leaf는 `_cap(s, _ARG_VALUE_CAP=500)`로 budgeted 캡.
   - **fail-closed**: 비문자 키 `str(k)`·깊이 상한(`_REDACT_MAX_DEPTH`)·전체 try/except → 실패 시 안전
     마커. 사이클/거대 중첩에 안 죽는다(learning 089 §4).
   - 적용: `_execute` args, `interrupt(...)` payload args, rag `_record` args.

2. **result 캡 (learning 059)** — `_execute`의 `result=text`가 calls_sink에 *무제한*으로 들어가
   거대 도구 결과가 trace를 부풀린다. `_cap(text, _RESULT_CAP=2000)`로 raw에서 캡(비밀 무관 독립 실거리).

### 잔존(정직 기록)

- **평범한 키에 담긴 값-비밀**(예: 도구 인자 `q`에 자격증명): 도구 스키마별 allowlist가 불가능하고
  args는 *보여주는 게 목적*이라 deny-by-default를 못 쓴다. → by-design 잔존. 단 시스템 자기 비밀이
  안 오고 admin 전용이라 실위험 낮음.
- **result 자유텍스트 비밀 에코**: 자유텍스트에서 비밀 정규식 추출은 신뢰 불가. → 캡만(DoS 방어),
  내용 redaction은 잔존.

## 완료 조건 / 검증

- **단위 (verify_087)**: 민감 키(top-level·중첩 dict·list 내부) 값 redacted·평범 키(query) 보존·긴
  문자열 캡·비문자 키 무크래시·깊이 상한 무크래시·result 거대 문자열 정직 캡·정상 result 무변경.
- **무회귀**: verify_041(HIL 실 MCP, args/result 흐름)·verify_086 그린.
- **적대 타자(codex)**: redaction 경계라 1런 — "마스킹한 키 말고 *남는* 누출 경로?"(여집합). 단 scope=B
  의 잔존(평범키 값·result 자유텍스트)은 *의도된 by-design*임을 명시.
- `tsc` 0(프런트 무변경이라 형식 확인만).

## 검증 결과 (4런)

- **단위 (verify_087)**: U1~U8b + C1~C2b + B1 + S1~S3 **전부 그린**. 민감 키(top·중첩·list) 마스킹·평범
  키 값 보존·긴 문자열 캡·비문자 키/깊이 상한 무크래시·미지 타입 타입명·result 캡·원천 3곳 호출 단언.
- **무회귀**: verify_086(노드 요약 redaction — `_SENSITIVE_KEY` 확장은 *더 많이* 마스킹할 뿐 회귀 0)·
  verify_041(HIL 실 MCP args/result 흐름) **그린**.
- **적대 타자(codex, 1런)**: redaction 경계라 "여집합" 1런. 3건 지적 — 모두 실재, 셋 다 수정·회귀잠금:

  | # | codex 지적 | 처분 | 회귀 가드 |
  |---|---|---|---|
  | F1 | `_SENSITIVE_KEY`가 `api_key`만 봐 `private_key`·`access_key`·`client_key`·`*_key` 표준 비밀명 누락 | `[_-]key$\|^key$` 추가(monkey/top_k는 구분자 없어 거짓양성 0) | C1·C1b |
  | F2 | `_redact_args`가 float 원문 통과 → NaN/Infinity가 JSONB(`Approval.args`)·엄격 JSON에 비유효 → commit 깨짐 | `math.isfinite` 검사로 `<nan>`/`<inf>` 안전 마커(fail-closed) | C2·C2b(`json.dumps(allow_nan=False)` 단언) |
  | F3 | rag `_record` result가 `_RESULT_CAP` 우회 | `_cap(result, _RESULT_CAP)` 적용 | S3 + U8 |

- **tsc**: 0(프런트 무변경 — 원천서 닫으므로 이미 redacted 데이터 수신).

## 비목표

- 086급 recursive value-allowlist(과한 금칠).
- 평범 키 값-비밀·result 자유텍스트 비밀의 완전 차단(by-design 잔존).
- 프런트 변경(원천서 닫으므로 불요).
