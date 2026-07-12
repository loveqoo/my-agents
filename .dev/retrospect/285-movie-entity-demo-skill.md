# 285 — 영화 엔티티 데모 로더 스킬 (스펙 311)

## 무엇을 했나
엔티티 RAG(스펙 149)의 첫 구동 예제 부재를 **모델 선택형 온디맨드 로더**로 메웠다. `movies.jsonl`
(행=1영화, metadata 숫자 id 여럿·data=줄거리) + `ingest_movie_entities.py`(모델 선택·`kind='entity'`
컬렉션 생성·인제스트·검색+meta 자가확인) + `.claude/skills/movie-demo`. dev에서 mock-embed로 실행 →
movies-demo 생성·10행 인제스트·검색 hit meta에 `movie_id` 노출·멱등·어드민 엔티티 탭 시각 확인.
스펙 310(엔티티 평가 판정)의 픽스처 공급원.

## 배운 것 / 복리 포인트

- **성숙한 코드베이스에선 "먼저 뭐가 있는지" 확인이 스캐폴딩의 절반 — 사용자의 반복된 회의가 세 번의
  done을 걸러냈다**. 이번 세션에서 후보로 올린 승인 화면(251)·권한 설정(199/200)·문서 RAG 평가(140)가
  **전부 이미 구현**이었고, 사용자가 매번 "이미 된 거 아니냐"로 멈춰 세워 실코드 확인 → done 확정 →
  진짜 갭(엔티티 RAG 평가)만 남겼다. 백로그 라인이 stale(251 완료를 반영 안 함)이라 내가 "1순위"로
  오인한 것도 여기서 드러났다. **후보를 낼 때 백로그를 신뢰하지 말고 실구현을 grep으로 재측정**하고,
  "이미 됐을 수 있다"를 기본 가설로 둔다. → [[probe-deeper-before-concluding]] [[surface-gilding-vs-core-proactively]]

- **데모/픽스처의 "의미 품질"은 임베딩 모델이 정한다 — 미리 real 벡터를 넣어도 질의가 같은 모델이라야
  의미가 산다**. "1024차원 데이터를 미리 넣자"는 사용자 발상의 함정: 첫 구동엔 mock-embed뿐이라, 미리
  넣은 real 벡터가 있어도 **질의가 mock으로 임베딩돼 다른 벡터공간** → 결과 깨짐. 벡터는 저장·질의가
  **같은 모델**이라야 비교된다. 그래서 "미리 real 벡터 주입"은 실모델 바인딩 전까진 무의미. 해법 =
  seed에 박지 말고 **모델 선택형 로더** — mock=결정적 픽스처(CI·310 평가), real=의미 데모(배포). 한
  도구가 두 목적. (RAG_EMBED_DIMS 기본 1024라 "1024차원"은 mock-embed로도 공짜.) → [[verification-ladder-three-rungs]]

- **seed에 박지 말고 온디맨드 로더로 — 최소 seed 보존 + 재사용 + 픽스처 겸용**. seed에 영화를 박으면
  (a) mock-embed라 비의미 데모 (b) seed 비대(스펙 303 최소주의 역행) (c) 모델 고정. 대신 `ingest_rag_
  samples.py` 계보의 스크립트+스킬로 빼면 seed는 깨끗하고, **어느 환경서든 원하는 모델로** 재적재되며,
  스펙 310 평가의 픽스처를 겸한다. 반복 태스크→스킬 도출(운영 매뉴얼). → [[structure-first-boundary-is-spec]]

- **엔티티 정체 = 파일명 아닌 metadata id들(가변·숫자) — 실데이터 스크린샷이 설계를 확정**. 사용자
  엔티티는 파일 1개에 N행이라 파일명 무가치. 실 검색화면 metadata(`{label_cate_id:null, sql_filter_id:3,
  column_info_id:18, sql_filter_key_id:3}`)를 보고 **부분 일치(키=값 부분집합)·숫자/null 가변**이 정답
  판정 형태임을 확정했다(스펙 310 rag_meta_contains 설계 근거). 추측 대신 사용자 실데이터로 설계.
  → [[playground-is-precision-debug-channel]]

## 검증 (사다리)
- **실 인프라(dev, mock-embed)**: 스크립트 → movies-demo(kind=entity) 생성·10행 인제스트(청크 10)·검색
  hit#1 meta=`{movie_id:101,director_id:1,genre_id:1}` 노출(스펙310 전제 충족)·**멱등 재실행 스킵**.
- **시각(브라우저)**: 어드민 'RAG 컬렉션' 엔티티 임베딩 탭에 movies-demo(mock-embed·1024·문서1·청크10·
  준비됨) 렌더 확인. (검색 패널 캡처는 셀렉터가 삭제 버튼을 눌러 미완 — 삭제 미확인, 컬렉션 온전 재확인.)
- **자가확인**: search_collections hit이 meta dict 반환·movie_id 실림을 스크립트가 단언.
- 스크립트는 scripts/(게이트 밖, ingest_rag_samples 계보) — mypy/ruff 대상 아님.

## 남은 것 / 주의
- **스펙 310(엔티티 평가 판정)**이 후속 — 이 movies-demo가 픽스처. 순서: 311(완료) → 310.
- mock-embed는 비의미(결정적) — 의미 데모는 실모델(이 dev엔 multilingual-e5-large-mlx도 등록돼 있어
  실모델 데모도 가능). 컬렉션 모델 불변(149)이라 모델 바꾸려면 새 컬렉션.
- 브라우저 캡처 셀렉터 교훈: 행 액션 버튼을 `.last()`로 잡으면 삭제(비가역)를 누른다 — 명시 셀렉터로.
- dev api(8000)·vite(5173) 기동 중.
