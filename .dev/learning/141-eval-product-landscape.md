# 141 — 조사: 타 제품 평가 설계 (플랫폼 5종 + RAG 전문 4종)

> 2026-07-03, 스펙 137~140 직후 사용자 지시("다른 프로덕트는 어떻게 하는지 살펴보고 논의하자")로
> 병렬 웹 조사(general-purpose ×2). 원문 보고서 전문은 이 파일 하단. 요약과 격차 분석만 위에.

## 업계 공통 설계 (플랫폼: LangSmith·Langfuse·Braintrust·promptfoo·OpenAI Evals)
1. **케이스 3요소**: input + **expected(골든 정답, 선택)** + metadata — 5종 공통.
2. **채점 3계층**: 결정적(코드/문자열) → LLM-judge → **인간 리뷰** — OpenAI만 인간 층 부재.
3. **비교 단위 = 고정 데이터셋 × 가변 구성(모델·프롬프트)** — 전원 공통. 사후 run 비교
   (LangSmith·Braintrust·Langfuse·OpenAI) vs 한 실행에서 격자(promptfoo: 컬럼=prompt×provider,
   행=케이스, Different 필터).
4. **기준선 대비 빨강/초록 회귀 하이라이트 + 회귀만 필터** — 수렴된 UI 문법(우리 138과 동일 발상).
5. 점수 결합=가중평균/수식(promptfoo weight·OpenAI multi·Braintrust aggregate).
6. **프로덕션 트레이스 → 데이터셋 수확 루프**(Langfuse source_trace_id·Braintrust·LangSmith).
7. judge 출력=점수+**사유**를 1급 필드로(우리도 139에서 동일).
8. 에이전트 평가=trajectory 분화(promptfoo `trajectory:tool-used/sequence/goal-success` — 우리
   trace_has와 같은 계열, 우리가 이미 가진 축).

## RAG 평가 표준 (Ragas·DeepEval·Phoenix·TruLens)
- 표준 셋 = 검색 2~3 + 생성 2: **Faithfulness/Groundedness**(응답 claim 분해→컨텍스트 지지율),
  **Answer Relevancy**, **Context Precision**(관련 문서 상위 랭크), **Context Recall**(정답 claim의
  컨텍스트 귀속률 — 유일하게 reference 필수). TruLens **RAG Triad**=무정답 최소셋.
- **같은 이름, 다른 계산**: Answer Relevancy가 Ragas=역질문+임베딩 코사인, DeepEval=LLM 분류.
  메트릭은 이름 아닌 **계산 절차**로 도입할 것.
- **검색만 결정적으로**: 골든 문서 매핑(질문→정답 문서 ID)만 있으면 NDCG/MRR/Hit Rate(TruLens·
  Phoenix)·IDBasedContextPrecision/Recall(Ragas) — 무비용·CI 상시.
- **골든셋 자동 생성**: Ragas Knowledge Graph 생성기(single/multi-hop × specific/abstract,
  페르소나)·DeepEval Synthesizer(진화 7종+critic 필터) — "골든셋 없어서 못 한다"는 틀린 전제.
- **judge 신뢰성**: Phoenix=judge 자체를 골든셋으로 벤치마크(F1 85%+ 템플릿만 제공),
  Ragas=인간 주석 15~20개로 judge 정렬(train), DeepEval=G-Eval(log-prob 가중)·rubric·strict.

## 우리(137~140)와의 격차
**이미 표준과 일치**: 케이스/런 구조·결정적+judge 2층·트레이스 assert(선도 축)·추이·기준선
회귀 하이라이트·judge 사유 저장·오염 제로 러너.
**빠진 것(중요도순)**:
1. **모델별 비교** — 업계 비교축의 핵심(구성 가변)이 우리엔 없음. 사용자 직접 제안과 일치.
2. **expected(골든 정답) 1급 필드** — output_contains로 우회 중(promptfoo식). 골든셋 생성·
   correctness judge의 전제.
3. **judge 신뢰성 장치** — 단일 judge PASS/FAIL뿐. 최소: 심판 성능을 골든 라벨로 측정.
4. **RAG 표준 메트릭** — 우리 3종(hits/score/source)은 IR 원시형. faithfulness류 없음.
5. **골든셋 자동 생성** — 컬렉션 문서에서 문제집 부트스트랩.
6. 인간 리뷰 층·점수 가중·프로덕션 세션→케이스 수확.

## 원문 보고서
(하단 두 절은 조사 에이전트 보고 전문 — 생략 없이 보존)
원문은 .dev/learning/141a-platforms-report.md·141b-rag-report.md 참조
