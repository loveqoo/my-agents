# 137 — mem0가 임베더에 차원을 강제해 self-hosted 임베더가 400 (스펙 159)

스펙 158 진단 정직화의 **직접 후속**: 158이 "정상·0건" 위장을 걷어내자 사용자 배포본이 진짜 에러를
드러냈다 — `Error 400: Model "snowflake-arctic-embed-l-v2.0" only supports [256] matryoshka dimensions`.

## 근인
`_build_config`가 임베더 config에 `embedding_dims=_EMBED_DIMS`(전역 env 1024)를 넣어, mem0
OpenAIEmbedding이 요청에 `dimensions=1024`를 강제 전송(openai.py: `_pass_dimensions_to_api =
embedding_dims is not None`). snowflake 서버는 명시 출력차원 256만 허용 → 400. **`MEM0_EMBED_DIMS`가
두 축을 겹쳐 씀** — (1) pgvector 컬럼 차원(저장 벡터 길이), (2) 임베더 요청 차원(API `dimensions`).
후자는 self-hosted 임베더엔 유해(모델 네이티브를 받으면 됨). RAG는 모델 차원을 probe하는데 mem0만 전역 강제.

## 배운 것
- **진단 정직화가 다음 버그를 낳는다(좋은 의미).** 158이 실패를 표면화하자마자 진짜 원인이 드러났다.
  "0건 위장"을 걷어내는 158이 없었으면 이 400은 영영 안 보였다 — 진단 투자→근인 노출→후속 수정의 사슬.
- **정적 기본값은 어느 쪽이든 한 케이스를 깬다(내 두 번의 오답).** ①"항상 전송"=snowflake(파라미터
  거부) 깨짐. ②내 첫 수정 "항상 미전송"=text-embedding-3류(네이티브≠컬럼, 파라미터 지원) 깨짐(codex
  High). 두 실패의 판별자는 **네이티브-vs-컬럼 관계**뿐이라 정답은 **probe**(RAG가 이미 하던 것). 정적
  분기로 자꾸 때우려던 게 함정 — 신호가 부족하면 측정(probe)이 답.
- **사용자의 사실 정정이 파괴적 조치를 막았다.** 내가 "11건은 다른 임베더 것→초기화" 권장했는데
  사용자가 "모델은 1024"라고 정정 → 11건은 같은 모델 네이티브 1024라 멀쩡, 초기화 불필요. **비파괴
  수정 전에 사용자 정정을 반영**([[probe-deeper-before-concluding]]). AskUserQuestion 답("초기화")도
  전제가 틀리면 무효 — 답의 글자보다 목표(작동하는 검색·데이터 보존)를 따른다.
- **캐시 키는 백엔드 신원과 같은 축이어야(codex High).** resolve_backend는 api_key로 백엔드를
  구분하는데 probe 캐시가 (base_url,model_id)만 쓰면 키별 라우팅 모델이 차원 오염 → 캐시 키는 상위
  캐시(백엔드)와 동일 축(+api_key)으로.
- **동기 probe는 상한을 걸어라(codex Med).** mem0 기본 OpenAI 클라 타임아웃 600s → blackhole 호스트가
  루프 직접 호출(broker 810/931)에서 오래 막음. 차원은 모델 속성이라 짧은 타임아웃·무재시도 평문
  임베딩 1회로 충분 → 자체 클라(timeout=10, max_retries=0)로 측정, mem0 임베더 우회.
- **env는 파싱 검증(codex Low).** `int(env)`를 config 조립부에 두면 잘못된 값이 백엔드를 죽인다(→
  resolve_backend가 None 캐시, 재기동까지 회복 불가). 전용 헬퍼로 걸러 경고만.
- **코드로 못 고치는 조합은 정직한 경계로.** 네이티브≠컬럼 AND 파라미터 거부 = 컬럼(고정)·모델
  근본 불일치 → 400을 진단(158)이 표면화 + 경고 로그. 고치는 척(다른 위장) 말고 경계 문서화([[complement-attack-can-be-honest-boundary]]).

## 검증
verify_159 15/15(네이티브==컬럼 미전송·네이티브≠컬럼 전송[codex 회귀 방지]·opt-in·probe실패 보수·env검증
·캐시키 api_key·로컬 왕복). codex 2라운드: R1 High1(정적 미전송 회귀)→probe 전환, R2 High1(캐시키)/
Med(타임아웃)/Low(env검증) 반영·측정, High2(불가 조합)=경계 문서화. 사용자 배포본 재조회 시 11건 실증 대기.

## OUT
- 컬럼 마이그레이션 도구·모델별 컬럼 차원 저장·arctic query-prefix 주입(158 OUT)·broker 810/931
  to_thread 전환(기존 Memory.from_config 루프 실행, probe는 타임아웃으로 상한).

[mem0,embed-dims,forced-dimensions-param,column-vs-request-axis,probe-not-static-default,honest-diagnostic-breeds-next-fix,user-correction-halts-destructive,cache-key-matches-backend-identity,bounded-sync-probe]
