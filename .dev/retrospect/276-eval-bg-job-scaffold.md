# 276 — eval 배경 작업 스캐폴딩 정본화 (스펙 301)

## 무엇을 했나
census 후보 D(최대 절감·중간 위험). `eval_authoring.py`의 4개 배경 작업이 반복하던 스캐폴딩을 원자화:
`_job_lock`(asynccontextmanager, discard만)·`_next_order_idx`·`_apply_completion_marker(ds,mark,tail)`·
`_stamp_failure(ds_id,msg)`·`_execute_append_job(*,generate,build_case)`(suggestion+generation_append 통합).
generation/harvest는 원자만 차용(본문 존치). 사용자 노출 문자열은 바이트 보존.

## 배운 것 / 복리 포인트

- **`--reload` dev 서버 + 배경 태스크 + 실모델 스위트 = 팬텀 회귀 제조기**. verify_209_harvest가
  "수확 0건"으로 실패해 **회귀로 오판**하고 오래 추격했으나, 실제로는 (a) 파일 편집마다 uvicorn `--reload`가
  lifespan(init_db=alembic+seed) 재실행하며 **in-flight 배경 harvest 태스크를 kill**, (b) 동시 실행 중인
  실모델 스위트가 **단일 프로세스 이벤트 루프를 점유**해 배경 태스크를 verifier의 10초 폴 밖으로 지연 —
  둘 다 태스크 미완→마커 미치환→`generating=True` 지속→폴 타임아웃→0건. **계측(ENTER/GOT/COMMIT 타임라인)을
  넣으니 정상 시 ~1.5초 완료·cases=2가 일관**되게 찍혀 코드 무결 확정. 교훈: **배경 작업 verifier가 플래키하면
  코드부터 의심 말고 서버 안정성(리로드·루프 점유)을 먼저 통제**하라. 조용한 서버(스위트 종료 후)에서 10/10 통과.
  → [[reload-reruns-migrations-mid-edit]] [[ui-verification-must-be-functional]]

- **플래키 판정의 정본 = 계측된 타임라인, 추측 아님**. "동일해 보이는 코드인데 왜 실패?"를 5번 넘게
  코드 정독으로 못 풀었다. `/tmp` 로그에 ENTER·GOT(cases 수)·COMMIT(made 수)·EXCEPTION을 시각과 함께
  찍자 **단 한 번에** "예외 0·항상 1.5초 완료·cases 정확"이 드러나 환경 아티팩트로 확정. 자가검증(정독)보다
  측정. → [[probe-deeper-before-concluding]]

- **배경 작업은 `_job_lock`(discard-only 컨텍스트매니저)로 봉인, add는 엔드포인트**. census 경고대로
  락 lifecycle 비대칭(add=엔드포인트 동기 획득=flood 가드 codex #1/#2, discard=배경 finally)을 지켜야
  했다. 컨텍스트매니저가 add까지 삼키면 flood 카운트 창이 열린다. generation의 **내부 중복 add는 제거**
  (엔드포인트가 이미 spawn 전 획득). → [[installed-guard-isnt-covering-guard]]

- **콜러블 주입으로 ~90% 쌍 통합, 억지는 배제**. suggestion↔generation_append는 생성기·케이스 빌더
  2개만 달라 `_execute_append_job(*, generate, build_case)`로 접었다. harvest는 flush+harvested_case_pk
  스탬프가 append와 달라(구조 상이) 원자만 차용하고 루프 본문 존치. generation은 order_idx=i·직접
  description이라 외곽(락+실패)만 차용. **본문 공유 정도에 맞춰 차등 적용**. → [[flow-dedup]]

## 검증 (사다리 3런)
- **단위/게이트**: metrics-fast 0(복잡도 감소). 인라인 스캐폴드 잔존 0(next-order·마커·finally 전부 원자).
- **실인프라 통합**: verify_209_harvest 조용한 서버 10/10 통과(계측 타임라인=예외0·1.5초·cases 정확).
  스위트 51/51. (verify_142/143은 Obsidian 시드 부재로 로직 이전 bail=환경 전제, 무관.)
- **적대(codex)**: 여집합 7축 — name/order_idx/asserts 바이트 동일·tail/마커/실패 문자열 보존·락 불변식·
  harvest 본문 보존·generation order_idx=i 보존 → "여집합 공격 실패 — 결함 없음".

## 남은 것 (backlog)
- verify_209_harvest 등 배경 verifier의 폴 타임아웃(10초)이 스위트 동시 실행 시 짧음 — 격리 실행 권장(문서화).
- eval_* 내부 잔여 중복 미전수·stale verifier 일괄 갱신.
