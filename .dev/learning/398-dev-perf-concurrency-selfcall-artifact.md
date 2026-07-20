# 398 — dev 성능 측정의 동시성 붕괴는 "자기-호스팅 mock + 단일 워커" 아티팩트

## 맥락
스펙 421(그래프 캐시) 후 배포 에이전트 성능 측정(tests/measure_perf.py — CPU·메모리·지연·동시성).
순차는 깨끗했으나 **동시 30요청에서 전 유형 붕괴**(성공 5~13/30, wall 30초, p95 30,000ms).

## 함정: "플랫폼이 동시성에 붕괴한다"고 단정할 뻔
30초라는 둥근 수 + 낮은 성공률 → "심각한 동시성 병목"으로 보고하기 쉽다. 하지만 [[probe-deeper-before-concluding]].

## 근인: 자기-HTTP-호출 × 단일 워커
- **mock-llm 모델의 base_url = `http://127.0.0.1:8000/_remote/v1`**(seed.py:253) — 매 채팅이 **같은
  서버로 자기-HTTP-호출**해 모델 응답을 받는다. mock MCP도 같음(`/_remote/mcp/`, _TOOL_TIMEOUT_S=30).
- 단일 워커에서 30개 채팅 SSE 핸들러가 **각자 자기-호출**을 대기 → 워커가 자기-의존으로 굶어 30초 타임아웃.
- 반증: mock 엔드포인트를 **직접** 30 동시로 때리면 30/30·0.02초(서버 raw 동시성은 멀쩡). 붕괴는 채팅
  경로의 **자기-의존 합성**이지 서버 천장이 아니다.

## 결정적 disambiguation: 다중 워커
`uvicorn --workers 4`로 재기동 후 동일 버스트:
- default·route·plan·orchestrate·pipeline-3 → **30/30, 0.2~0.5초, 100+ req/s**(완전 해소).
- pipeline-8만 잔존(20/30, 30초) — uncached 26ms 그래프 빌드가 매 요청 이벤트루프 블록 + 8노드 자기-호출
  팬아웃(8배 증폭).

## 교훈(How to apply)
- **자기-호스팅 mock(모델·MCP가 같은 서버)로는 동시성/처리량을 측정하지 마라** — 단일 워커면 자기-의존이
  거짓 붕괴를 만든다. 프로덕션은 외부 모델(async I/O가 이벤트루프 반환) + N 워커라 다르다.
- 동시성 판정 전 **워커 수를 변수로** 갈라라(1 vs N). N에서 해소되면 자기-호출/단일워커 아티팩트, N에도
  남으면 공유 자원(DB 풀·락) 또는 uncached 빌드의 이벤트루프 블록(→ 캐싱이 실약).
- **순차 CPU/빌드 측정은 모델과 무관**(빌드는 모델 호출 前)이라 mock서도 유효 — 캐시 가치는 여기서 읽어라.
- pipeline-8 잔존은 스펙 421 **P3(pipeline 캐싱)**이 실제로 겨냥하는 지점(26ms/요청 상각).

[[cpu-axis-not-latency]] [[observe-before-remedy-remote-env]] [[research-prior-art-before-expensive-probing]]
관련 자산: tests/measure_perf.py(신규), tests/measure_build_cpu.py, 스펙 421.
