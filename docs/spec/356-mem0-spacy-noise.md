# 356 — mem0 spaCy 경고 정리 (엔티티 메모리 미사용)

## 왜

콘솔에 "mem0 라이브러리 설치 실패"로 보인 메시지의 정체:
`Failed to load spaCy lemma/full model: spaCy is not installed. Install it with pip install mem0ai[nlp]`
(`mem0.utils.spacy_models` 로거의 WARNING 2줄).

**무해하다**: spaCy는 mem0의 **BM25 하이브리드 검색용 lemmatization**에 쓰인다(`main.py`의
`lemmatize_for_bm25` — 메모리 저장 add마다 호출해 `text_lemmatized` 메타데이터 생성). spaCy가 없으면
**원문을 그대로 반환하는 fallback**이라, 검색은 정상 작동하고 lemmatization 품질만 약간 낮아질 뿐이다.
mem0 본체도 정상 초기화된다. 즉 설치 실패가 아니라 **optional 미설치 + 정상 fallback**.

**"왜 예전엔 안 보였나"(개발자 질문, 규명)**: 예전에도 **항상 났다**. ①`mem0ai>=2.0.7`은 mem0 최초
도입(6/23, 커밋 e01fc8c)부터라 BM25 lemmatization은 처음부터 있었고, ②이 경고는 `_load_failed_lemma`
전역 플래그로 **서버 프로세스당 딱 1회**(첫 메모리 저장 시 로드 시도→실패→캐시→이후 조용)다. 오래 떠
있던 서버의 누적 로그에선 그 1~2줄이 묻혔는데, 데이터 초기화 + **콜드 재기동 후 로그를 처음부터**
봐서 이번에 눈에 띈 것이다. 데이터 초기화가 경고를 새로 만든 게 아니다.

**정정(probe-deeper 실패)**: 초판은 spaCy를 "엔티티/그래프 메모리 전용"으로 적었으나 틀렸다 —
BM25 lemmatization용(저장 경로)이다. "안 쓰는 기능"이 아니라 "쓰지만 fallback으로 충분한 품질 보조"다.

## 설계

무거운 의존성(`spacy>=3.7.0` + 언어 모델 수십 MB)을 **품질 보조**(fallback으로 이미 작동)를 위해
추가하지 않는다. 대신 이 로거만 정확히 눌러 노이즈를 없앤다: `mem0.utils.spacy_models` → ERROR.
다른 mem0 경고는 유지. 결합은 `mem0_backend.py`(mem0를 가둔 모듈)에 둔다.
(엔티티 검색 정밀도를 실제로 높이고 싶어지면 그때 `mem0ai[nlp]`를 정식 추가 — OUT.)

## 완료 조건

- **S1** 부팅/mem0 초기화 시 spaCy WARNING 0(로거 억제 확증: import 시 레벨 NOTSET→ERROR, WARNING 미발화).
- **S2** mem0 본체는 무회귀(초기화·회상·저장 정상).

## 결과 (2026-07-15)

- `mem0_backend.py`에 `logging.getLogger("mem0.utils.spacy_models").setLevel(logging.ERROR)`.
- 확증: import 전 레벨 0(NOTSET) → 후 40(ERROR), `isEnabledFor(WARNING)=False`. 서버 부팅 로그 spaCy 0.

## OUT

- 엔티티/그래프 메모리를 **실제로 쓰게 되면** 그때 `mem0ai[nlp]` + 언어 모델을 정식 의존성으로 추가(별 스펙).
