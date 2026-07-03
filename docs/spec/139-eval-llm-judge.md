# 139 — 평가 3탄: LLM-judge (비결정 채점 축)

## 배경 / 왜
결정적 채점(도구 사용·문구 포함)으로 못 재는 "답변 품질"(정중함·요약 정확성 등)을 **다른 모델이
판정**하는 보조 축. 119 설계대로 결정적 점수와 분리된 축 — 비결정성을 명시하고 fail-closed로 다룬다.

## 설계
1. **assert type `llm_judge`**(arg=판정 기준 문장, 500자 캡 기존 재사용). build_asserts 닫힌 집합에
   추가 — scorer는 `obs["judge"][criterion]["pass"]`를 읽는다(부재=False, fail-closed).
2. **심판 실행(eval_judge.py)**: `run_llm_judge(question, output, criterion, llm_cfg)` —
   심판 모델=**기본 chat 모델**(is_default, mem_config 선례 재사용). OpenAI 호환
   /chat/completions 직접 호출(temperature 0). 프롬프트: "엄격한 심판. 첫 줄에 PASS 또는 FAIL만,
   둘째 줄에 한 문장 이유." **파싱은 순수 함수 `_parse_verdict`** — 첫 줄이 PASS/FAIL 외면
   판정 실패=False+사유(형식 오류도 실패로 — 조용한 초록 금지). 이유는 300자 캡 저장.
3. **러너 통합**: _execute_run의 run_fn에서 obs 획득 후, 그 케이스의 llm_judge asserts만 순차 심판
   호출 → `obs["judge"]`에 주입(HarnessCase.meta로 raw asserts 전달). 기본 chat 모델 미설정이면
   전 judge=False+사유 "심판 모델 미설정"(fail-closed). 심판 호출 예외도 False+사유.
4. **UI**: assert 편집기에 "AI 판정" 유형(힌트: 판정 기준 문장 예시). 성적표 관측에 **판정 이유** 표시
   (judge 항목별 기준·PASS/FAIL·이유 — 비결정 축임을 라벨로 명시).

## 검증
- 단위: _parse_verdict(PASS/FAIL/형식오류/여분텍스트) · build_asserts llm_judge 매핑 · scorer
  fail-closed(judge 부재=False).
- 통합(실 로컬 모델): 쉬운 기준("답변이 한국어인가")→PASS, 불가능 기준("답변이 오직 숫자로만
  구성됐는가")→FAIL — temp 0으로 사실상 결정적.
- e2e(fast-worker): AI 판정 기준 포함 문제집 실행 → 성적표에 judge 행+이유. codex 간이(프롬프트
  인젝션—답변이 심판 지시를 뒤집는 경우·이유 캡·미설정 fail-closed).

## 비목표 (OUT)
- 심판 모델 선택 UI(기본 chat 모델 고정 — 선택은 후속), 다중 심판 합의, RAG 평가 러너(다음 차례).
