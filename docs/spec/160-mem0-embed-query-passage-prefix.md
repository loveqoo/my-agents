# 160 — mem0 임베딩 query/passage 접두어 주입(설정형, 비대칭 모델용)

## 배경 (스펙 158·159 OUT)
e5·arctic 등 **비대칭 임베딩 모델**은 검색어에 `query:`, 문서에 `passage:`(또는 arctic처럼 query만)
접두어를 붙여야 학습된 공간에서 제대로 매칭된다. mem0 OpenAIEmbedding은 `memory_action`(add/search)을
**무시하고 원문 전송**(openai.py:47) → 접두어가 안 붙는다.

## 측정 (로컬 e5, 추측 금지)
접두어 없음/양쪽/검색만 3방식 실측: 정답 5/5 동일, 분리도 +0.062 / +0.063 / **+0.069**(검색만).
→ (1) **e5는 접두어 효과 미미**(순위 어차피 정확). (2) **검색만 접두어가 해롭지 않다**(기존 raw 저장을
안 건드려도 됨 — 비파괴). 배포본 arctic은 로컬 재현 불가지만 arctic-v2.0은 **query 접두어·passage raw**
설계라 기존 11건(raw 저장) 그대로 두고 검색에만 붙이면 정합 → 재인덱싱 불필요.

## 설계
- **설정형(하드코딩 금지, 정적 기본값 함정 회피)**: env `MEM0_QUERY_PREFIX`·`MEM0_PASSAGE_PREFIX`,
  기본 `""`(no-op → 무회귀). 배포본은 arctic이면 `MEM0_QUERY_PREFIX="query: "`(passage는 빈값).
- **memory_action 기준 주입**: `Mem0Backend.__init__`이 `Memory.from_config` 후 `_mem.embedding_model`의
  `embed`/`embed_batch`를 감싸, `memory_action=="search"`면 query 접두어, 그 외(add/update=저장)면
  passage 접두어를 앞에 붙인다. 접두어 둘 다 빈값이면 래핑 스킵(순수 no-op).
- 비파괴: 기본 무동작. arctic은 passage 빈값이라 저장 경로 무변경(기존 11건과 정합), 검색만 접두어.

## 검증
- verify_160: (V1) 기본(env 미설정) → 래핑 안 함(embed 원문 그대로). (V2) query/passage 설정 →
  search는 query 접두어·add는 passage 접두어가 실제 embed 텍스트에 붙음(스파이로 측정). (V3) embed_batch도
  저장 접두어 적용. (V4) 로컬 실 e5 add+search 왕복(접두어 설정) 동작(무회귀). (V5) arctic 모사(passage
  빈값·query만) → 저장 텍스트 무변경·검색만 접두어.
- codex 여집합. 배포본에서 arctic 접두어 켜고 회상 품질 실측(최종).

## 경계 (codex 160 확인)
`MEM0_PASSAGE_PREFIX`를 **기존 raw 벡터가 있는 운영 DB에 나중에 켜면** old(raw)/new(passage) 저장
벡터가 혼재한다(코드가 재인덱싱을 자동 보장 안 함). 안전위반 아닌 운영 경계 — **arctic 배포는
`MEM0_QUERY_PREFIX`만 켜는 비파괴 모드**(passage 빈값 → 저장 무변경, 기존 11건 정합)로 쓴다. passage
접두어까지 쓰려면 빈 DB에서 시작하거나 재인덱싱 필요.

## OUT
- 모델별 접두어 UI/스키마(env로 충분, 배포본 임베더 1개). 접두어 자동 감지(모델명→접두어 매핑) —
  하드코딩 위험, 설정형이 안전. e5 미미 효과는 측정으로 확인됨(과한 금칠 금지). passage 접두어용 재인덱싱 도구.
