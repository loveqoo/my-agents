# 046 — per-operation 타임아웃은 전체 작업의 deadline이 아니다

## 상황
서버측에서 외부 URL을 **스트리밍**으로 읽을 때(`httpx.AsyncClient(timeout=10)` +
`client.stream(...)` + `async for chunk in r.aiter_bytes()`), "타임아웃 10초를 걸었다"는
말이 "이 호출은 10초 안에 끝난다"를 뜻하지 않는다.

## 교훈
**httpx의 `timeout`은 per-operation(읽기 1회·연결 1회) 한도지, 작업 전체의 벽시계 budget이
아니다.** 악성·오작동 서버가 1바이트씩 9초마다 흘리면(slow-trickle / "Slowloris"식) 매 read는
한도 안이라 통과하고, 연결과 서버 코루틴은 raw 바이트 상한에 닿을 때까지 — 잠재적으로 수 시간 —
붙잡힌다. raw 바이트 캡(learning 041)이 있어도 *시간*은 안 막힌다(캡은 메모리를 막을 뿐).

→ 스트림 전체를 `asyncio.timeout(전체_deadline)`으로 한 번 더 감싸라. per-read 타임아웃과
전체 deadline은 **둘 다 있어야** "타임아웃 방어"가 참이 된다.

```python
async with asyncio.timeout(_STREAM_DEADLINE):          # 전체 벽시계 budget
    async with httpx.AsyncClient(timeout=10) as client:  # per-read 한도
        async with client.stream("GET", url) as r:
            async for chunk in r.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > _MAX_BYTES: ...            # 메모리 캡(learning 041)
```

## 언제 떠올리나
서버측 fetch/probe/스트림에 "타임아웃을 걸었다"고 적을 때. 특히 응답 본문을 **스트리밍/청크**로
읽는 경로. 단언 전에 물어라: "이 타임아웃의 적용 범위가 read 1회냐, 작업 전체냐?"

## 메타패턴 — "서브유닛에 건 방어는 전체를 못 묶는다"
세 축이 같은 함정이다:
- **WHERE 카운트** — 프레임/버퍼 위가 아니라 *원천 바이트*에서 세야 캡이다(learning 041).
- **WHICH URL** — 가드는 최초 URL만 보고 redirect 체인 끝은 못 본다(learning 044).
- **WHICH span** — 타임아웃은 read 1회만 묶고 스트림 전체는 안 묶는다(본 학습).

공통 처방: 방어를 적을 때 **그 방어의 적용 단위(sub-unit vs whole)를 같은 줄에 명시**하면,
적대 리뷰가 아니라 작성 시점에 경계가 드러난다. 검증은 단위 테스트로 못박는다(여기선 slow-trickle
대역 + `_STREAM_DEADLINE`을 작게 패치 → deadline 차단 단언; `tests/verify_047_catalog.py` S6).

근거: 스펙 047, 적대 서브에이전트 리뷰가 MAJOR로 적발 → 같은 턴에 수정+S6 커버. 회고 036.
