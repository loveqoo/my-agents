# 141a — 원문: LLM/에이전트 평가 플랫폼 조사 (2026-07-03, 조사 에이전트 보고 전문 요지)

## LangSmith (docs.langchain.com/langsmith/evaluation-concepts, compare-experiment-results, prebuilt-evaluators, github.com/langchain-ai/openevals)
- 데이터 모델: Dataset=example 컬렉션. Example={inputs, reference outputs(선택·평가자만 참조=골든셋), metadata}. Experiment=특정 앱 버전을 데이터셋에 평가한 결과(출력·점수·트레이스). 오프라인(정답 대비) vs 온라인(무정답) 구분.
- 스코어러 4종: Code(결정적)·LLM-as-judge(reference-free/based/few-shot)·Human(Annotation queue, Pairwise 큐)·Pairwise. feedback={key, score/value, comment}. openevals: CORRECTNESS/CONCISENESS/HALLUCINATION/RAG_HELPFULNESS/RAG_GROUNDEDNESS/RAG_RETRIEVAL_RELEVANCE 프롬프트, exact match, Levenshtein, embedding similarity, JSON match, 코드 타입체크·E2B 실행. 에이전트용 agentevals 별도.
- 비교: 같은 데이터셋의 experiment 2+개 선택→Compare. Compact/Full view, Diff view(2개 한정, 텍스트 차이), "Set as source experiment"(기준선).
- 회귀: source 대비 회귀 run=빨강·개선=초록, feedback 컬럼 헤더에 개선/악화 카운트, 회귀만 필터. 점수 방향 컬럼별 설정.
- 트레이스: run이 child run(도구·LLM 호출) 포함, trajectory 평가는 agentevals, 비교 뷰에 Traces mode.

## Langfuse (langfuse.com/docs/evaluation/*)
- Dataset item={input, expected_output, metadata}(전부 선택), JSON Schema 강제, 미디어 첨부, **버저닝**(item 변경마다 새 버전·시점 조회), source_trace_id로 프로덕션 유래 기록.
- 스코어러: LLM-judge(Managed 카탈로그+Custom 템플릿 {{input}}/{{output}}/{{ground_truth}}, JSONPath 매핑+라이브 프리뷰)·Code·Human(Annotation Queues). Score=Numeric/Categorical/Boolean+reasoning.
- 비교: Experiments UI — 프롬프트 버전×모델 연결 선택, 결과 테이블 집계 점수 side-by-side. Score Analytics로 시간 추이. CI/CD 회귀 차단.
- 트레이스: judge를 observation-level(권장)로 실행. 선언적 트레이스 assert는 미확인.

## Braintrust (braintrust.dev/docs/guides/evals*)
- Eval(project, {data, task, scores}). 케이스={input, expected, metadata, tags, trialCount(반복 시행→버킷 집계)}.
- 스코어러: Code({name,score})·autoevals(Factuality/Levenshtein/Battle/Summary/ClosedQA/NumericDiff)·Human review 워크플로(Unreviewed/Assigned to me 필터)·Classifiers.
- 비교: experiment 간. UI 요약 패널 "Comparisons to other experiments", diff mode(side-by-side), 메타데이터 Group by.
- 회귀: "Order by regressions", SQL 쿼리 필터, Aggregate scores(수식 결합).
- 트레이스: 각 행=완전한 trace, spans view(타이밍·토큰), 온라인 스코어링+프로덕션 트레이스→데이터셋 끌어오기.

## promptfoo (promptfoo.dev/docs/*)
- YAML: prompts × providers(모델+config) × tests. 테스트={vars, assert}. vars 파일 참조(CSV/JSONL/Sheets…), 배열=전 조합. 골든값은 assert 안에. defaultTest 공통 적용.
- assert 결정적: equals/contains/icontains/regex/starts-with/is-json/is-sql/javascript/python/webhook/levenshtein/rouge-n/bleu/latency/cost… 모델 채점: llm-rubric/g-eval/factuality/similar(임베딩)/answer-relevance/context-faithfulness/context-recall/context-relevance/classifier/moderation. 전 타입 not- 부정형. 인간: 웹 UI rating/comment 영속.
- **matrix가 1급**: eval 한 번에 prompts×providers 전 조합 × 전 케이스. UI: 컬럼=prompt×provider, 행=케이스, Display mode(All/Failures/**Different**/Highlights), 검색·지표 필터.
- 집계: 테스트 점수=assert 가중평균(weight), threshold, assert-set(그룹 비율 임계). 실행 간 Compare(diff green/red)+Scatter Plot.
- **트레이스 최강**: 자체 OTLP 수신기(4318), GenAI 시맨틱 자동 계측. **trajectory:tool-used / tool-args-match / tool-sequence / goal-success + trace-span-count/duration/error-spans**.

## OpenAI Evals (developers.openai.com/api/docs/guides/evals, graders)
- Eval={data_source_config(JSON 스키마), testing_criteria}. 데이터=JSONL item(골든 라벨 포함). Run=eval을 특정 모델+프롬프트로 실행. result_counts/per_testing_criteria_results/per_model_usage.
- 그레이더: string_check(eq/ne/like/ilike)·text_similarity(fuzzy/bleu/rouge…+threshold)·label_model(분류 judge)·score_model(점수 judge)·python(def grade)·**multi(calculate_output 수식 결합)**. 인간 층 없음(5종 중 유일).
- 비교: eval=불변 시험지, run=응시 — 축이 API 설계에 내장. 회귀 하이라이트 UI 상세 미확인.

## 공통 패턴 8
1. 케이스 3요소(input+expected+metadata) 2. 채점 3계층(결정적→judge→인간) 3. 비교="고정 데이터셋×가변 구성" (사후 비교 vs promptfoo 격자) 4. 기준선 빨강/초록 회귀 문법 5. 가중/수식 점수 결합 6. 프로덕션 트레이스→데이터셋 수확 7. judge=점수+사유 1급 8. trajectory 평가 분화.
