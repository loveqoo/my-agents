# 381 — 큰 모듈 분할: verbatim 슬라이스 + re-export로 임포터 무변경, 순환은 지연 import로

## 맥락

캠페인 374 Tier 2에서 god-file 3개를 쪼갬 — schemas.py(1054줄·76클래스, 스펙 378)·models.py(765줄·
30모델, 379)·runtime.py의 RAG 도메인(380). 전부 **동작 불변**(전후 SUITE_OK·e2e 39/39·수치 보존)으로 착지.

## 교훈 (재사용 기법)

- **verbatim 슬라이스로 전사 오류 0.** 본문을 손으로 옮기지 말고 원본 줄 범위를 스크립트로 잘라
  새 모듈에 그대로 쓴다. 헤더는 넉넉히 얹고 `ruff check --fix --select F401`로 미사용 import를 자동
  정리(모듈별로 다른 import를 손으로 고르지 않는다). **보존은 측정**: 분할 후 클래스/모델 수가 원본과
  같은지 카운트로 확인(378=76·379=30 일치).
- **패키지 `__init__` 명시적 re-export로 임포터 무변경.** `schemas.py`→`schemas/` 패키지로 바꿔도
  `from api.schemas import X`는 __init__이 재수출하면 그대로 뚫린다. blast radius가 큰 파일일수록 이게
  이득(수십 임포터를 안 건드림). SQLAlchemy 모델은 __init__이 **전 모델을 import**해야 레지스트리에
  등록돼 relationship 문자열 참조가 해결된다(configure_mappers()로 검증).
- **모듈 속성 접근(`runtime.search_collections`) 소비자는 re-export가 정답.** 소비자가
  `from .runtime import X`가 아니라 `runtime.X` 속성 접근을 쓰면, 옮긴 심볼을 원 모듈이 재수출해
  호출부를 하나도 안 고친다.
- **re-export가 순환을 부르면 지연 import로 끊는다.** runtime이 rag_runtime을 재수출하는데
  rag_runtime이 runtime 헬퍼를 쓰면 모듈 레벨 상호 import=순환. 해법: **피추출 모듈이 원 모듈 헬퍼를
  함수 내 지연 import**한다(모듈 로드 시엔 단방향, 헬퍼는 호출 시점에 resolve). 그럼 원 모듈의
  모듈 레벨 재수출이 순환을 안 만든다. 앱 import + 실제 호출(build_rag_tool 실빌드)로 검증.
- **경계 판단 = 무엇을 남기고 무엇을 옮기나.** 옮기는 도메인 안에 정의됐어도 **다른 섹션이 쓰는
  공용 유틸(_sanitize_preview)은 원 모듈에 남긴다** — 안 그러면 원 모듈이 피추출 모듈을 역참조해
  순환. "물리 위치"가 아니라 "누가 쓰나"로 가른다.
- **config per-file-ignore도 파일과 함께 옮겨야 한다.** schemas.py의 N815(camelCase 필드) ignore를
  패키지로 안 옮기면 45개 오탐이 뜬다 — 분할은 코드뿐 아니라 그 파일을 가리키던 설정도 갱신 대상.
- **함수 사이 모듈 레벨 상수는 함수단위 블록 추출이 못 따라간다(rag.py 분할서 실증).** 슬라이스가
  함수 경계로만 자르면, 함수 *사이*에 낀 `_LOCKABLE_STATUSES = (...)` 같은 상수는 물리적으로
  직후에 오는 route 블록에 딸려가 엉뚱한 도메인 모듈로 오배치된다(그 상수를 쓰는 shared 헬퍼가
  F821). 봉합: ruff F821을 신호로 삼아 **"누가 쓰나"로 shared 귀속을 수동 판정**(keep-shared-util-in-
  origin의 상수판). 헬퍼 목록에만 없는 공유 상수(`MAX_UPLOAD_BYTES`)는 소비 모듈의
  `from .shared import`에 상수를 명시 추가. → 분할 후 **ruff 전 F821 목록을 상수 오배치 체크리스트로** 본다.

[verbatim-slice-no-transcription-error, package-init-reexport-preserves-importers,
count-preserved-measure, sqlalchemy-registry-import-all, attribute-access-consumer-needs-reexport,
lazy-import-breaks-reexport-cycle, keep-shared-util-in-origin, move-updates-config-too,
between-func-constant-misplaced-by-block-slice]
