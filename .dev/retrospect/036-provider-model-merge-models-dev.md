# 036 — 프로바이더·모델 통합 + models.dev 카탈로그 회고

스펙: `docs/spec/047-provider-model-merge-models-dev.md`
마스터: `044`(2026-06-28 어드민 테스트 14건) 배치3 — #6(kind/description 라벨)·#7(models.dev 카탈로그)·#8(프로바이더·모델 메뉴 통합).

## 무엇을 했나
- **#8 메뉴 통합**: `ProvidersView`+`ModelsView` 두 화면 → 단일 마스터-디테일 `ProviderModelView.tsx`.
  좌측 프로바이더(kind 배지·설명·모델 수), 우측 디테일에서 `[GET /models]`로 실모델 나열·토글 등록.
- **#7 카탈로그**: models.dev 스냅샷(`data/models_dev.json`, 2656 엔트리)을 `catalog.py`로 박제,
  `lookup(full→bare→None)`. 등록된 모델에 context/cost/modalities/capabilities 메타 자동 첨부.
- **#6 라벨**: `Provider.kind`(local|mock|remote)/`description` 컬럼+시드 문구, `ModelConfig.meta` JSONB.
- 신규 엔드포인트 `GET /providers/{id}/available-models` — 실모델 + registered 플래그 + 카탈로그 메타.

## 검증 사다리(3 rung + 타자)가 또 값을 했다
- 단위(`verify_047_catalog.py`)·통합(`verify_047_integration.py`, self-fixture로 시드 비결합 — learning 045)·
  마이그레이션 왕복·회귀·브라우저샷까지 전부 GREEN으로 굳힌 **뒤** 적대 서브에이전트에 넘겼다.
- 적대 리뷰는 "Ship, BLOCKER 0"이면서도 **실제 결함 2건**을 집어냈다 — 셀프 GREEN이 "결함 없음"이
  아니라 "내가 상상한 실패만 없음"임을 또 확인(메모리 `adversarial-review-before-destructive-ship`).

## 적대 리뷰가 잡은 것 — 둘 다 "방어를 깔았다 ≠ 방어가 작동한다"
1. **per-read 타임아웃이 전체 deadline이 아니다(MAJOR).** 스펙은 SSRF 표면에 "타임아웃"을 방어로
   명시했는데, `httpx.AsyncClient(timeout=10)`은 **읽기 1회** 한도다. 1바이트씩 9초마다 흘리는
   slow-trickle 응답은 매 read가 한도 안이라 통과하고, 연결(과 서버 코루틴)을 raw 바이트 상한
   도달까지 — 잠재적으로 수 시간 — 붙잡는다. 스펙의 방어 주장이 **거짓**이 되는 지점.
   → `asyncio.timeout(_STREAM_DEADLINE=20)`으로 스트림 전체에 벽시계 deadline을 따로 걸었다.
   per-read와 전체-deadline은 **둘 다 있어야** "타임아웃" 주장이 참이 된다. → learning 046.
2. **삭제 가드가 버전 스냅샷을 안 봤다(MINOR).** 가드가 `Agent.model`/`config.model`(live)만 검사해,
   아카이브된 `AgentVersion.config["model"]`이 참조하는 모델을 지운 뒤 그 버전으로 롤백하면 런타임이
   사라진 모델을 가리킨다(가드의 존재 이유 자체가 위반됨). → 버전 스냅샷 카운트도 가드에 추가(별도
   409 메시지). 통합 I5b로 커버.

## 잘한 판단
- **거짓 주장을 남기지 않았다.** MINOR라 fast-follow로 미룰 수도 있었지만, 045 배치 전체가 "정직화"
  였고 스펙이 timeout을 방어로 주장하니 지금 고쳐 주장을 참으로 만들었다. 작고 안전한 수정.
- **수정마다 테스트를 같이 깔았다.** S6(slow-trickle deadline)·I5b(버전 스냅샷 가드) — 다음 회귀에서
  자동으로 지켜진다. "고쳤다"가 아니라 "고쳤고 못박았다".
- self-fixture 통합(045 학습 적용)으로 데모 시드와 비결합 — 시드가 바뀌어도 이 통합 rung은 안 죽는다.

## 다음에 더 잘할 것
- 스펙에 "방어: 타임아웃" 같은 줄을 쓸 때, **그 방어의 적용 범위(per-op vs whole-op)를 같은 줄에
  적자.** 그러면 적대자가 아니라 작성 시점에 경계가 드러난다(learning 044의 작성측 버전).

## 연결
- learning 046(per-read ≠ 전체 deadline), 044(가드 적용 범위), 041(원천 바이트 캡) — 같은 메타패턴
  "서브유닛에 건 방어는 전체를 못 묶는다"의 세 축(WHERE 카운트 / WHICH URL / WHICH span).
- learning 045(self-fixture로 rung 보존) 적용처.
