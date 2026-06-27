# 041 — "리밋"은 *원천 바이트*를 막아야 한다 — 선버퍼링·프레임 카운트는 캡이 아니다

> 출처: 스펙 042 A2A 실호출 적대 리뷰. 관련: [[038-adversarial-review-finds-what-invariants-miss]],
> [[037-floor-the-destructive-knob]], [[040-real-infra-integration-catches-glue-and-deployment-drift]].

## 증상

외부 응답에 `MAX_RESPONSE_BYTES` 캡을 "걸었다"고 믿었는데, 적대 리뷰가 둘 다 무력임을 보였다:

1. **단건 경로:** `resp = await client.post(...)`; `raw = resp.content[:MAX]`. `resp.content`는 슬라이스
   *전에* 본문 **전체를 메모리에 버퍼링**한다 — GB 응답이면 슬라이스에 닿기 전에 OOM. 캡은 장식이었다.
2. **스트림 경로:** `async for line in resp.aiter_lines(): total += len(line)`. `aiter_lines`는 개행이
   올 때까지 **내부 버퍼를 무한히 키운다** — 공격자가 `data: ` 뒤로 개행 없이 GB를 흘리면 한 줄도
   yield되기 전에 다 쌓인다. 줄당 카운트는 줄이 완성된 *뒤*에야 도므로 영원히 안 돈다.

두 경우 모두 happy-path 단위·통합·목 테스트는 **초록**이었다(작은 응답엔 캡 위치가 안 드러남).

## 교훈

**캡은 데이터가 들어오는 *가장 낮은 층*(raw 바이트 스트림)에서 누적분을 세야 한다.** 상위 추상화가
주는 편의(`.content` 전체 본문, `.aiter_lines()` 완성된 줄)는 *이미 버퍼링을 마친* 산물이라, 그 위에서
자르거나 세는 건 "막은 척"이다. 진짜 바운드:

```
total = 0
async for chunk in resp.aiter_bytes():     # raw 바이트, 청크 단위
    total += len(chunk)
    if total > MAX: return error            # 줄·JSON 완성 여부와 무관하게 즉시 차단
    buf += chunk; ... 직접 프레이밍 ...
```

같은 함정의 일반형: "리밋이 *전제하는 단위*가 공격자가 통제하는 단위인가?" 줄 수 캡은 무개행 입력에,
항목 수 캡은 거대 단일 항목에, 페이지 캡은 무한 단일 페이지에 뚫린다. **리밋은 공격자가 못 키우는
단위(raw 바이트·시간)로 걸어야 한다.**

## 적용 규칙

- 외부/신뢰불가 응답을 읽을 땐 `.content`·`.text`·`.aiter_lines()`·`.json()` 같은 **선버퍼링 추상화
  금지**. `.aiter_bytes()`로 누적 바이트를 직접 세고 상한서 끊는다(단건도 stream으로).
- 캡을 짤 때 **"이 카운터가 도는 시점이 버퍼가 이미 큰 뒤인가?"**를 자문한다. 뒤면 캡이 아니다.
- happy-path 테스트는 캡 위치 결함을 못 본다 — **적대 입력(거대·무개행·무한)** 픽스처나 적대 리뷰로만
  드러난다. 부수효과·자원 캡 같은 안전 손잡이는 [[037-floor-the-destructive-knob]] + 적대 검증을 같이.
- 곁가지: 외부 호출 제너레이터는 **절대 raise 안 함**을 불변식으로(모든 실패→error 프레임+done). 비-HTTP
  예외(키 회전 시 decrypt RuntimeError 등)도 try 범위에 넣어 광역 except로 프레임화 — try 밖 한 줄이
  스트림을 done 없이 끊는다.
