# 356 — mem0 spaCy 경고 정리 (엔티티 메모리 미사용)

## 왜

데이터 초기화 후 콘솔에 "mem0 라이브러리 설치 실패"로 보인 메시지의 정체:
`Failed to load spaCy lemma/full model: spaCy is not installed. Install it with pip install mem0ai[nlp]`
(`mem0.utils.spacy_models` 로거의 WARNING 2줄).

**무해하다**: spaCy는 mem0의 **엔티티/그래프 메모리** 전용 optional extra인데, 우리는 그 기능을 안
쓴다(`_build_config`에 graph_store 없음 — llm·embedder·vector_store만). mem0 본체는 정상 초기화되고,
빠지는 건 엔티티 어형(lemma) 처리뿐이다. 즉 설치 실패가 아니라 **안 쓰는 optional 미설치**.

## 설계

무거운 의존성(`spacy>=3.7.0` + 언어 모델 수십 MB)을 안 쓰는 기능 때문에 추가하지 않는다. 대신 이
로거만 정확히 눌러 노이즈를 없앤다: `mem0.utils.spacy_models` → ERROR. 다른 mem0 경고는 유지.
결합은 `mem0_backend.py`(mem0를 가둔 모듈)에 둔다.

## 완료 조건

- **S1** 부팅/mem0 초기화 시 spaCy WARNING 0(로거 억제 확증: import 시 레벨 NOTSET→ERROR, WARNING 미발화).
- **S2** mem0 본체는 무회귀(초기화·회상·저장 정상).

## 결과 (2026-07-15)

- `mem0_backend.py`에 `logging.getLogger("mem0.utils.spacy_models").setLevel(logging.ERROR)`.
- 확증: import 전 레벨 0(NOTSET) → 후 40(ERROR), `isEnabledFor(WARNING)=False`. 서버 부팅 로그 spaCy 0.

## OUT

- 엔티티/그래프 메모리를 **실제로 쓰게 되면** 그때 `mem0ai[nlp]` + 언어 모델을 정식 의존성으로 추가(별 스펙).
