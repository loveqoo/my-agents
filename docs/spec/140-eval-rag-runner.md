# 140 — 평가 4탄: RAG 컬렉션 평가 러너 (kind='rag')

## 배경 / 왜
사용자 요청(137 승인 시): "비슷하게 수집된 rag도 평가하는 도구". 컬렉션이 **질문에 맞는 근거를
실제로 찾아주는가**를 문제집으로 상시 측정 — 인제스트 품질·임베딩 모델 교체·문서 추가의 회귀를
같은 평가 화면(추이·비교 포함)에서 본다. 137이 마련한 kind='rag' 축의 완성.

## 설계
1. **러너 eval_run_rag(collection, query)**: rag.py 시험 엔드포인트와 같은 해석(_load_collection
   완전성/kind 가드) + `search_collections` 공유 코어(평행 구현 금지 — 072 교훈). obs =
   {output: format_rag_hits(결과), trace_nodes: ["rag:{name}"], error, rag: {hits:[{score,filename,
   text캡}], top_score}}. 검색 실패는 error obs(fail-closed).
2. **RAG 전용 assert 3종**(닫힌 집합 확장, obs["rag"] 부재=False fail-closed — agent 런에 쓰면 실패):
   - `rag_hits_gte`(arg=정수): 검색 결과가 N건 이상
   - `rag_score_gte`(arg=0~1 실수): 최고 유사도가 임계 이상
   - `rag_source_contains`(arg=문자열): 근거 파일명에 포함(특정 문서가 근거로 나와야 함)
   기존 재사용: output_contains(결과 본문 문구)·no_error·**llm_judge**(검색 결과 관련성 AI 판정).
3. **실행 분기**: RunStartIn에 collection_id 추가(agent_id와 택일) — dataset.kind로 검증
   (agent→agent_id 필수, rag→collection_id 필수). EvalRun.agent_name에 대상 박제("RAG · {이름}").
   judge 주입은 kind 무관 공통.
4. **UI**: 새 문제집 모달에 종류 선택(에이전트 시험/RAG 컬렉션 시험). rag 문제집 드로어는 에이전트
   대신 **컬렉션 선택**. assert 편집기에 rag 3종 추가(힌트 포함). 실행 이력 컬럼명 "대상"으로.

## 검증
- 단위: 3종 매핑·fail-closed(rag 부재)·arg 형식 검증(정수/실수 파싱 실패=ValueError).
- 통합(실 Obsidian 컬렉션): "A/B 테스트" 질의 → hits>0·source에 해당 노트·score 임계, 오염 제로
  (rag 검색은 읽기 전용이라 자명하나 세션 카운트 핀 유지).
- e2e(fast-worker): rag 문제집 생성→컬렉션 선택→실행→성적표(검색 결과 본문·score 확인). codex 간이.

## 비목표 (OUT)
- 인제스트 품질 자동 진단(청크 크기 튜닝 등), 다중 컬렉션 동시 평가, 골든셋 자동 생성.
