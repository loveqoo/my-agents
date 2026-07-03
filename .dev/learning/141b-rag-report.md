# 141b — 원문: RAG 평가 방법론 조사 (2026-07-03, 조사 에이전트 보고 전문 요지)

## Ragas
- Faithfulness: 응답→claim 분해→컨텍스트 지지율(LLM). HHEM-2.1(T5 분류기) 대체 변형(저비용).
- Answer Relevancy: 응답에서 역질문 생성(기본 3)→원 질문과 임베딩 코사인 평균(하이브리드).
- Context Precision: chunk 관련성 LLM 판정→mean Precision@k(랭킹 가중). Context Recall: reference를 claim 분해→컨텍스트 귀속률(reference 필수).
- **비-LLM 변형 체계적**: NonLLMContextPrecision/Recall(문자열 유사도), **IDBasedContextPrecision/Recall(문서 ID 집합 — 순수 결정적)**.
- **골든셋 생성(최정교)**: Knowledge Graph 기반 — Splitter→Extractors(NER 등)→Relationship Builders→Query Synthesizers. **Single/Multi-hop × Specific/Abstract** 2×2 + 페르소나. 산출=(user_input, reference_contexts, reference).
- 에이전트: ToolCallAccuracy(시퀀스 정렬×인자 정확도, strict/flexible)·ToolCallF1·AgentGoalAccuracy·TopicAdherence.
- judge 신뢰성: 인간 주석 15~20개로 judge 프롬프트를 gradient-free 최적화(metric.train()).

## DeepEval
- RAG 5메트릭 전부 LLM-judge(self-explaining=점수+사유): Faithfulness(claim 모순 검사)·Answer Relevancy(statement 분류 — Ragas와 계산 다름!)·Contextual Precision/Recall/Relevancy.
- 골든셋 Synthesizer: from_docs/contexts/scratch/goldens. **Evolution 7종**(REASONING/MULTICONTEXT/CONCRETIZING/CONSTRAINED/COMPARATIVE/HYPOTHETICAL/IN_BREADTH)+critic 필터(Filtration)+Styling.
- 에이전트(최다): **Tool Correctness(결정적 코어 — tools_called vs expected_tools, 인자·순서 옵션)**+Task Completion/Argument Correctness/Step Efficiency/Plan Adherence/Plan Quality.
- judge 신뢰성: **G-Eval(log-prob 가중 정규화)**·Rubric(구간 명시)·strict mode(이진화)·DAG 메트릭(판단을 의사결정 트리로 분해→결정적).

## Arize Phoenix
- 사전 벤치마크된 eval 템플릿(Hallucination/QA Correctness/Retrieval Relevance/Toxicity…) — 분류 라벨 중심. code evaluator 병행.
- **고전 IR 최명시**: 문서 단위 relevance 주석→**NDCG·Precision@K·Hit Rate 자동 계산**. "전통 검색 지표 반드시 보라" 권고.
- 골든셋 생성기 없음 — 질문 100~200+인간 정답 관행 문서화.
- 에이전트: Tool Calling/Selection/Parameter Extraction/Planning/Reflection 템플릿, Agent Trajectory eval(경로 LLM 분류), Path Convergence(경로 일관성 0~1).
- **judge 자체를 벤치마크(차별점)**: 템플릿마다 골든셋 대비 precision/recall/F1 공개(F1 85%+ 목표). AI vs Human groundtruth 일치도 워크플로.

## TruLens
- **RAG Triad**: Context Relevance·Groundedness·Answer Relevance — **무정답(reference-free) 최소셋**, 프로덕션 온라인용.
- feedback function 스펙트럼: 전통 NLP↔중형 모델↔LLM↔인간↔골든셋 일치(확장성 vs 의미성 트레이드오프 명시). groundedness=문장 분해→0~10 지지도(CoT 사유), 기권=grounded.
- 검색: GroundTruthAgreement — **NDCG@k/Precision@k/Recall@k/MRR/IR Hit Rate**(골든 문서 매핑 기반 쿡북).
- 골든셋 생성기·에이전트 특화 메트릭은 문서상 미확인.

## 표준 요약 + 놓치기 쉬운 것 3
- 표준=검색 2~3(Context Precision/Recall±Relevance)+생성 2(Faithfulness/Groundedness, Answer Relevancy). Context Recall만 reference 필수. RAG Triad=무정답 최소셋.
- ①같은 이름 다른 계산 — 절차 기준으로 도입. ②judge 성능을 재지 않는 것 — 골든 라벨로 벤치마크+정렬이 표준 관행. ③검색 평가를 LLM에만 의존 — 골든 문서 ID 매핑이면 결정적·무비용·CI 상시, 그 매핑도 자동 생성 가능("골든셋 없어서 못 쓴다"는 틀린 전제).
