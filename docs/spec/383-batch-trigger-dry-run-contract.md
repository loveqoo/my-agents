# 383 — 배치 트리거 dry_run 계약 경화 (+ verify_233 격리 정정)

> 상태: 초안(AI 작성 → 인간 검토). 성격: 안전 계약 버그 봉합.
> 참고: learning 037(파괴적 노브 바닥) · [[gate-on-intent-value-not-mutable-baseline]] ·
> [[product-limits-need-explicit-approval]] · [[verify-premise-before-designing]] · 회고 383(test-all 오염)

## 배경 — 안전 플래그가 위험값을 기본으로 갖는다

`POST /admin/batch/{job}/run`(batch_routes.py:122)이 dry_run을 **query에서만** 읽는다:

```python
async def trigger(job: str, dry_run: bool = Query(False)) -> dict:
```

배치 잡은 거의 다 **가장 비가역한 삭제 잡**이다 — session·checkpoint·token·approval·history·memory·user
cleanup(전부 `is_delete_all_pattern` delete-all 가드를 둔 "파괴적 노브 바닥"). 그런데:

1. 클라이언트가 `{"dry_run": true}`를 **body로** 보내면 FastAPI가 body를 선언조차 안 해 **조용히 무시** →
   기본값 `False`로 떨어져 **진짜 삭제 실행**. 흔한 클라이언트 실수(body vs query)가 파괴로 직행.
2. 안전 플래그의 기본값이 **위험쪽(false=진짜 실행)**. "플래그 없으면 진짜 삭제"는 파괴적 잡에서 뒤집힌 기본값.

소비자 실측(변경 안전성 근거):
- 관리자 UI: `triggerBatchJob`이 **항상** `?dry_run=${dryRun}` 명시 전달(api.ts:207) → 기본값 미의존.
- cron/스케줄러: `run_job`을 HTTP 없이 **직접** 호출 → 엔드포인트 계약과 무관.
- ⇒ 기본값을 뒤집어도 UI·cron 불변. 바뀌는 건 **맨몸 API 호출자의 "플래그 없음" 경로**뿐(=없애려는 위험).

## 목표

배치 트리거를 **안전쪽으로 기운 계약**으로 경화한다.

1. dry_run을 **body(JSON)에서도** 읽는다(흔한 실수 봉합, 조용한 무시 제거).
2. 기본값을 **안전쪽(dry_run=true)**으로 뒤집는다 — 진짜 실행은 **명시적 dry_run=false**를 요구.
3. 정밀도: **body > query > 기본값(true)**. UI(query)·맨몸 호출자(body) 둘 다 명확.

## 구현

`batch_routes.py`:

```python
class TriggerBody(BaseModel):
    # StrictBool(codex 적대리뷰 P1): 파괴적 잡이라 body는 진짜 JSON boolean만. 강제변환 허용 시
    # {"dry_run":"off"}·0·"no"가 조용히 False(진짜 실행)로 떨어진다 → 모호값은 422로 거부.
    dry_run: StrictBool | None = None

@router.post("/{job}/run", dependencies=[_run])
async def trigger(
    job: str,
    body: TriggerBody | None = None,
    dry_run: bool | None = Query(None),
) -> dict:
    if job not in JOBS:
        raise HTTPException(status_code=404, detail=f"미지의 작업: {job}")
    # 안전 기본값: 어느 소스도 명시 안 하면 dry-run(파괴적 노브 바닥).
    resolved = (body.dry_run if body and body.dry_run is not None else dry_run)
    resolved = True if resolved is None else resolved
    return await run_job(job, dry_run=resolved)
```

- 명시 소스가 둘 다 있으면 body 우선(맨몸 호출자의 body가 UI의 query와 어긋날 일은 실무상 없음 — 한 클라이언트가
  둘 다 보내지 않음. 규칙만 명시).
- 관리자 UI는 query만 보내므로 `body=None` → query 값 사용(dry_run=false 실행 버튼도 그대로).

## 완료 조건(측정 가능) — verify_383

인프로세스 `httpx.ASGITransport`(verify_110/233 패턴), 슈퍼principal override, 파괴 없는 잡(예:
가장 안전한 조회형/또는 dry_run이 실제 삭제 안 하도록 보장된 잡) 대상:

- **C1 기본값 안전**: query·body 둘 다 없이 POST → 응답이 dry-run(실행 안 함). `BatchRun.dry_run == true`.
- **C2 body 존중**: body `{"dry_run": true}` + query 없음 → dry-run. (구 계약은 진짜 실행 = 회귀 여집합)
- **C3 명시 실행**: query `dry_run=false` → 진짜 실행(`BatchRun.dry_run == false`). UI 실행 버튼 보존.
- **C4 정밀도**: body `{"dry_run": true}` + query `dry_run=false` → body 우선(dry-run).
- **C5 UI 경로 보존**: query `dry_run=true` → dry-run(관리자 UI dry-run 버튼).
- **C6 StrictBool 거부**(codex P1): body `{"dry_run":"off"|0|"no"|"false"}` → 422(강제변환 금지, 조용한 위험 실행 차단).
- **C7 역 정밀도 박기**: body false + query true → body 우선 → 진짜 실행(body>query 규칙의 위험 방향 회귀 고정).

**결과: verify_383 10/10 PASS(VERIFY383_OK). codex 적대리뷰=P1 1건(StrictBool)만 봉합, 나머지 축
"결함 없음—경계는 정직"(무body·빈JSON·extra-only=dry-run / malformed·text-plain·빈query=422).**

## 곁다리 — verify_233 격리 정정(오경보)

`run_suite.py:67`의 KNOWN_DRIFT 사유는 "orchestrate_ranked broker_invoke:agent 노드 부재"인데, **단독
실행하면 통과**한다(VERIFY233_OK, `orchestrate_ranked × agent` = PASS, 25 PASS/17 IGNORE-OK). 노드는 있고
발동한다 — test-all 상태 오염이 만든 가짜 실패(회고 383 패턴). **코드 결함 아님.** 조치:

- KNOWN_DRIFT 사유를 정직하게 정정: "제품결함 후보"가 아니라 **"단독 통과·test-all 상태 오염 격리"**.
  (233은 http 층이라 씨앗 그물서 빼는 게 맞고, 사유만 사실로 고친다.)

## 아웃(이번 스펙 밖)

- 다른 파괴적 write 엔드포인트의 dry_run 계약 전수(이번은 배치 트리거 한 곳) — 필요 시 후속.
- 배치 트리거에 실행 확인(confirm) 2단계 — 지금은 dry-run 기본값이 그 역할.
