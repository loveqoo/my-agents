# 391 — 지운 행이 마이그레이션 데이터 시드로 부활한다: 삭제는 생성 지점 전수 후에

## 맥락

스펙 387이 죽은 "단기(세션)" memory_types 행을 라이브 DB에서 삭제 → 다음날 DB 초기화 →
**드롭다운에 재등장**(개발자 적발: "왜 없애지 않았지?"). 범인 = alembic 리비전 c1d2e3f4a5b6
(옛 카탈로그 재정렬)이 **데이터 시드로 그 행을 INSERT** — fresh DB 부팅(upgrade head)마다 부활.
387 때 생성 지점 추적을 seed.py까지만 하고 `alembic/versions/`를 grep 범위에서 빠뜨렸다.
봉합 = 새 리비전(40079d14052f)이 체인 끝에서 DELETE(기존 리비전 불변 유지) + verify_387에
virgin-DB 단언(C1) 고정.

## 교훈

- **행 삭제는 "지금 지우기"가 아니라 "생성 경로 전수 차단"이다.** 데이터를 만드는 경로는 최소
  셋: seed(seed_if_empty)·**alembic 데이터 시드**·런타임 저작. 라이브 행만 지우면 마이그레이션이
  fresh DB마다 되살린다. 죽은 데이터 정리 시 grep 범위에 `alembic/`을 반드시 포함
  ([[installed-guard-isnt-covering-guard]]의 데이터판 — 지운 곳과 만드는 곳이 어긋난 틈).
- **마이그레이션 속 데이터 시드 수정은 새 리비전으로.** 기존 리비전을 고치면 이미 적용된 DB와
  미래 fresh DB의 결과가 갈린다(비결정). 체인 끝 DELETE는 양쪽 최종 상태를 동일하게 만든다
  (멱등 DELETE + 다운그레이드 대칭 INSERT).
- **fresh-DB 회귀는 virgin-DB 검증기로만 고정된다.** 라이브 DB에서 통과하는 단언은 초기화
  회귀를 못 잡는다 — verify_387이 asgi 층(스크립트당 virgin DB, 스펙 385)이라 C1 단언이 곧
  "마이그레이션 체인 끝 상태" 검증이 됐다. 385 하네스의 예상 못 한 배당.
- **덤 관찰**: 리비전 파일 54개 중 ID 파싱 상 중복 의심 4건([[hand-authored-migration-ids-collide-silently]]
  재점검 후보 — 이번엔 head 단일·DB 일치 확인만 하고 미추적).

- **추가 표본(같은 날 2회차)**: 행만이 아니라 **문구도 부활한다** — 장기 블록의 설명을 라이브
  PUT으로 고쳤지만(387), 같은 마이그레이션 시드가 옛 문구를 INSERT해 초기화 후 화석이 되살아났다.
  라이브 데이터 수정(행 삭제든 문구 갱신이든)은 전부 같은 질문을 통과해야 한다: "fresh DB에서도
  이 상태인가?" — 아니면 마이그레이션 체인 끝에 실어라(40079d14052f·7218f9ea87d7).

[deletion-must-cover-creation-paths, migration-data-seed-fix-via-new-revision,
fresh-db-regression-needs-virgin-verifier, grep-alembic-for-dead-data]
