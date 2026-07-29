# 스펙 430 — 외부 의존성 호출 정책 관문(타임아웃·재시도 단일 대장)

## 발단

kpas 비교 분석(2026-07-29, 구남님 공유)의 #2 "외부 의존성 운영 가드 — MCP/A2A/DB별 타임아웃·재시도·
서킷브레이커·fallback을 공통 정책으로". 7개 항목 중 유일하게 (a) 실측으로 확인된 실제 빈틈이고
(b) 회사 층이 아닌 온전한 우리 몫이라 채택([[verify-premise-before-designing]] — 전제를 grep 전수로 실측).

## 감사 결과(2026-07-29 grep 전수 — [[learning 149]] 기억 말고 전수)

| 의존성 | 호출부 | timeout | retry | fallback |
|---|---|---|---|---|
| **모델(chat 본선)** | model.py build_chat_openai | **미설정 → SDK 기본 600s 암묵** | **미설정 → SDK 기본 2회 암묵** | 연결실패 시 mock 힌트 문구만 |
| 모델(eval 4곳) | eval_harvest·golden·judge·suggest | 30/30/30/60 각자 하드코딩 | 0 | 0 |
| A2A 위임 | a2a_client | 120 (상수) | 0 | stream 404/405→send 1회(081) |
| MCP 도구 | runtime_mcp(+net_guard) | 30 전체 deadline(046) | 0 | 0 |
| 에이전트 카드 fetch | agent_card | 15 / 5 (두 곳 다름) | 0 | 0 |
| provider/모델 probe | providers·model_registry | 10 / 10 | 0 | — |
| RAG URL 인제스트 | rag_ingest | 60 | 0 | 0 |
| mem0 probe | mem0_backend | 10 (max_retries=0 명시) | 0 | 0 |
| mem0 llm/embedder 본선 | mem0 라이브러리 내부 | 통제 밖(라이브러리 기본) | 통제 밖 | 0 |
| DB | db.py | pool_pre_ping만(403) | — | — |

**진단**: ①가장 중요한 의존성(모델 본선)이 **우리가 고른 적 없는** SDK 기본에 방치. ②같은 부류(LLM 생성)
가 4곳에서 제각각 하드코딩. ③재시도는 전무(암묵 SDK 2회 빼면) — 일시 장애(콜드 스타트·재기동)에
전부 즉사. ④정책이 "어디에 뭐가 걸려 있나"를 아무도 한눈에 못 봄(이 표가 처음).

## 결정 — 정책 서술자 대장 + 관문(스펙 409/411 PARAMS 패턴 미러)

[[policy-at-the-chokepoint]][[extend-generic-not-parallel-hardcode]]: 파라미터를 서술자 한 줄로 관문화한
것처럼, 외부호출 정책도 **의존성 클래스별 서술자 대장 한 곳**으로.

### `packages/agent/src/agent/net_policy.py` (신설 — 정본 대장; agent 층 — 모델 관문(reasoning_chat)이 agent에 있고 api→agent 단방향이라 양쪽 공유 가능한 유일 층)

```python
@dataclass(frozen=True)
class CallPolicy:
    key: str            # 의존성 클래스 식별자
    timeout_s: float    # 전체 deadline(per-read 아님 — learning 046)
    retries: int = 0    # 멱등 호출만 >0 (백오프: 0.5s * 2^n)
    note: str = ""      # 왜 이 값인가(선정 근거)

POLICIES = (
    CallPolicy("model.chat",   timeout_s=180, retries=0, note="본선 생성 — 긴 사고/생성 허용, 비멱등이라 재시도 0(중복 생성 방지). SDK 암묵 600s→명시 180s"),
    CallPolicy("model.eval",   timeout_s=60,  retries=1, note="평가 계열(judge/golden/harvest/suggest) 통일 — 읽기성 생성, 1회 재시도"),
    CallPolicy("a2a.delegate", timeout_s=120, retries=0, note="기존 A2A_TIMEOUT_S 흡수 — 위임은 비멱등"),
    CallPolicy("mcp.tool",     timeout_s=30,  retries=0, note="기존 _TOOL_TIMEOUT_S 흡수 — 도구는 부수효과 가능, 재시도 0"),
    CallPolicy("card.fetch",   timeout_s=10,  retries=1, note="카드 조회 — 멱등 GET, 15/5 두 값을 10으로 통일"),
    CallPolicy("probe",        timeout_s=10,  retries=0, note="연결 probe — 빠른 실패가 목적이라 재시도 없음"),
    CallPolicy("rag.embed",   timeout_s=60,  retries=1, note="인제스트 임베딩 배치 — 멱등 POST(첫 표기 URL다운로드는 오독, 구현서 교정)"),
    # 구현서 추가 흡수: web.fetch 8 · mcp.discover 15(첫 감사 맹점 — codex 적중)
)
```

- `policy(key)` 조회 + `call(key, host, fn)`(브레이커+백오프 재시도 일체 — 구현서 단일 헬퍼로 통합)
  + `check/record_success/record_failure/release`(스트림 관문용 저수준).

### 서킷브레이커(구남님 교정으로 IN — 첫 안의 "과설계" 기각이 틀렸음)

첫 안은 브레이커를 "대량 트래픽 연쇄장애 방지"로 보고 OUT 했으나, 구남님이 교정: 개인 사용의 실제
고통은 **행(hang) 반복**이다 — 죽은 의존성(연결은 되는데 멈춤·블랙홀)에 매 요청이 타임아웃을 꽉 채워
기다린다(모델 180s면 요청마다 3분 대기→실패 반복). 브레이커가 열리면 두 번째부터 **즉시 실패 + 명확한
표면화**("회로 열림 — N초 후 자동 재시도")로 방어한다.

- **상태**: 프로세스-로컬 `(policy_key, 대상 host)` 별 — 연속 실패 카운트·마지막 실패 시각.
  (host 단위라 atom-spark이 죽어도 MLX·mock은 무영향. 단일 프로세스라 로컬 dict로 충분 — k8s 공유는 후속.)
- **전이**: 연속 실패 ≥ **threshold(3)** → open(**cooldown 30s**) → 경과 후 half-open(1회 시도) →
  성공이면 close·실패면 다시 open. 성공 1회는 카운트 리셋.
- **열림 시 동작 = 빠른 실패 + 표면화**: 남은 cooldown 초를 담은 명확한 오류(채팅은 SSE error frame,
  eval/probe는 해당 오류 경로). **대안 경로 폴백은 클래스별로 안전한 것만**:
  - A2A stream→send(081, 기존 유지) · MCP 도구 실패→에이전트가 도구 오류 보고 적응(기존 동작).
  - **모델은 다른 모델로 조용히 갈아타지 않는다** — 스펙 428 "선언과 다른 실행 금지"와 정합.
    모델 회로 열림 = 큰 소리 빠른 실패(mock 전환 힌트 문구는 기존 유지).
- **적용 대상**: 반복 호출로 행이 누적되는 클래스만 — `model.chat`·`model.eval`·`a2a.delegate`·
  `mcp.tool`. probe/card.fetch/rag.ingest_url은 산발 호출이라 제외(threshold에 안 닿음 — 노이즈만).
- **성공/실패 판정**: 타임아웃·연결 오류만 실패로 센다. HTTP 4xx(권한·잘못된 요청)는 의존성 건강과
  무관하므로 회로에 안 센다(안 그러면 설정 실수가 회로를 열어 오진).

### 호출부 이관(대장 참조로 교체 — 하드코딩 소멸)

1. **model.py build_chat_openai**: `ChatOpenAI(..., timeout=policy("model.chat").timeout_s, max_retries=0)`
   — 암묵 SDK 기본을 명시 정책으로(가장 중요한 수리). 클라이언트 풀 키에 이미 반영됨(생성 인자).
2. eval 4곳: `_GEN_TIMEOUT`/`_JUDGE_TIMEOUT` 제거 → `model.eval` 참조(+재시도 1).
3. a2a_client: `A2A_TIMEOUT_S` 제거 → `a2a.delegate` 참조.
4. runtime_mcp: `_TOOL_TIMEOUT_S` 제거 → `mcp.tool` 참조.
5. agent_card 15/5 → `card.fetch`(10)+재시도 1. providers/model_registry/mem0 probe → `probe`.
6. rag_ingest 60 → `rag.embed`+재시도 1. (+구현서: served_mcp→`web.fetch`, blocks_mcp_discovery→`mcp.discover`,
   broker/providers/mcp.py도 mcp.tool — 직접·브로커 같은 회로 공유.)

### 관측(가시성)

- `GET /admin/net-policies`(read-only): 대장 그대로 노출 — "어디에 뭐가 걸려 있나"를 API로.
  (kpas #5의 지표 대시보드는 회사 층 — 우리는 정책 가시화까지만.)

## 완료 조건(측정) — 결과

`tests/verify_430_net_policy.py` 22/22:
1. ✅ 하드코딩 소멸(grep 전수 재확인 — 잔여는 주석 산문뿐). codex가 첫 감사의 맹점 1곳 적중:
   asyncio.timeout(15)(blocks_mcp_discovery)는 httpx만 grep한 그물 밖 → `mcp.discover`(15) 흡수.
2. ✅ 모델 본선 timeout=180·max_retries=0 실측(U2 — SDK 암묵 600s·재시도2 소멸).
3. ✅ 멱등 재시도(U4)·비일시 즉시 전파·회로 미기록(U5).
4. ✅ 브레이커 전이 전부(U3): 3연속→열림(남은 초 표면화)·host 격리·성공→닫힘·half-open 1회+경쟁
   차단·실패→재열림·breaker=False no-op.
5. ✅ 실채팅 무회귀(신선 nonce, qwen36+thinking — 200·정상 응답)·그물 green.
6. ✅ codex 적대 검토 — **P1 5건 전부 실결함 인정·봉합**(U6 회귀 고정):
   - half-open 고착: 판정불가 종료(GeneratorExit·비일시 오류)가 trial_pending을 영영 남김 →
     `release()` 신설, 모든 관문(reasoning_chat·a2a·MCP 2경로·call)에 배선.
   - A2A 조기이탈=성공 오염: `_net_ok` 3상태(완주만 성공, 이탈=release)로 교체.
   - transient 오분류: ConnectError만 보던 판정이 mid-stream RST·EOF(ReadError·RemoteProtocolError)
     를 놓침 → `httpx.TransportError` 전체로 확장.
   - timeout 의미 부정직: httpx 경로는 per-phase(행 감지)지 전체 deadline이 아님 — 대장 docstring
     정직화(전체 deadline은 asyncio.timeout 배선 클래스만).
   - 회로 키 URL 노출·격리 이탈: `_norm_host()`로 host 접기(같은 서버 다른 경로=한 회로,
     userinfo 스냅샷 미노출).

## OUT(경계) — codex 정직화 포함

- **브레이커 상태의 멀티 인스턴스 공유**(프로세스-로컬 — k8s 백로그와 합류).
- **모델 회로 열림 시 대체 모델 폴백**(스펙 428 원칙과 충돌 — 필요해지면 "고지된 폴백"으로 별도 승인).
- **재시도 중 회로 열림이 원래 오류를 가림**(codex P2, 미문서→문서화): 임계 직전 상태에서 첫 시도
  실패가 회로를 열면 재시도 check가 CircuitOpenError로 바뀜 — "재시도 1회 보장"이 아니라 "회로가
  허용하는 한 재시도"가 계약(회로 우선이 의도 — 죽은 의존성에 재시도 낭비 방지).
- **스트리밍 총 벽시계는 의도적으로 무한**(codex P1 정직화의 이면): model.chat 180s는 per-phase
  행 감지 — 청크가 계속 흐르는 긴 생성은 정당해서 안 끊는다. 신뢰경계 밖 느린-드립 방어가 필요한
  곳은 호출부 wall-clock(providers 선례)·수신자 캡(a2a MAX_RESPONSE_BYTES)이 담당.
- **eval 5xx 재시도 없음**(HTTPStatusError는 transient 아님 — 서버가 살아 응답한 것. 5xx 재시도가
  필요해지면 별도 결정).
- **DB 풀 정밀 설정**(pool_size 등 — k8s 백로그와 합류, 403의 pre_ping으로 현재 충분).
- **mem0 라이브러리 내부 llm/embedder 타임아웃**(라이브러리 설정 표면 조사 필요 — 별개 후속).
- **fallback 일반화**(A2A stream→send·mock 힌트 현행 유지 — 클래스별 특성이라 공통화 이득 없음).
- kpas #1(스키마 템플릿)·#4(플레이북)·#3 테넌시·#5 대시보드·#6 카나리 — 회사 층/금칠(발단 절 참조).
