---
name: movie-demo
description: 영화 엔티티 데모 컬렉션을 임베딩 모델을 골라 심는다(스펙 311). 엔티티 RAG(스펙 149)를 첫 구동/데모에서 보여주거나, 엔티티 평가(스펙 310 rag_meta_contains)의 실측 픽스처가 필요할 때 사용. "영화 데모 심어줘", "엔티티 RAG 데모 만들어줘", "엔티티 평가 픽스처 넣어줘", "movies-demo 적재"에 사용.
---

# 영화 엔티티 데모 로더 (스펙 311)

`packages/api/data/entity_samples/movies.jsonl`(행=1영화, `metadata`에 숫자 id 여럿 `movie_id`·
`director_id`·`genre_id`, `data`=줄거리)을 **고른 임베딩 모델**에 바인딩된 `kind='entity'` 컬렉션에 적재한다.
seed는 손대지 않는다(온디맨드 로더).

## 왜 모델을 고르나 (핵심)
컬렉션의 임베딩 모델은 **생성 후 불변**(스펙 149) — 로드 시 목적에 맞는 모델을 골라야 한다.
- **`mock-embed`** → 1024차원·**결정적**(해시 벡터, 의미 아님) → 스펙 310 `rag_meta_contains` 평가의
  **결정적 픽스처**·CI. 검색 순위는 일관되나 의미 검색은 아님.
- **실 임베딩 모델**(예 `snowflake-arctic-embed`) → **진짜 의미 검색** 데모("우주에서 고립된 사람"→
  인터스텔라). 데모 품질은 여기서.

## 절차

### 1. 임베딩 모델을 고른다 (사용자 확인 — 필수)
등록된 임베딩 모델을 열거하고 하나 고른다. 기본은 기본 임베딩 모델(스크립트가 `is_default`→첫 임베딩
순으로 자동 선택). 목적을 물어 갈라라: **평가/CI 픽스처면 `mock-embed`, 의미 검색 데모면 실모델**.
열거 예: `cd packages/api && uv run python -c "import asyncio,sys; sys.path.insert(0,'src'); from sqlalchemy import select; from api.db import SessionLocal; from api.models import ModelConfig; asyncio.run((lambda: None)())"`
— 또는 어드민 '프로바이더·모델' 화면/‎`GET /models`로 kind=embedding 목록 확인.

### 2. 라이브 서버 전제 확인
선택 모델의 임베딩 엔드포인트가 도달 가능해야 한다(mock은 앱 내 `/_remote/v1/embeddings`, 실모델은
그 원격). dev면 api 서버(127.0.0.1:8000)가 떠 있어야 한다. 사용자가 외부 접속이면 **서버 기동은 직접**
한다(승인만) — SSH 금지, 이 호스트 로컬만.

### 3. 적재
```
cd packages/api && uv run python scripts/ingest_movie_entities.py --model <모델명> [--collection movies-demo]
```
스크립트는 컬렉션 생성(있으면 재사용)·`movies.jsonl` 적재(파일 단위 멱등)·검색 1회로 **hit의 meta에
movie_id 등 id가 실려 나오는지**까지 자가확인한다. `[done] … → 성공`이면 완료.

### 4. 확인·안내
- 어드민 'RAG 컬렉션'에서 `movies-demo`(엔티티)와 검색 결과의 metadata를 눈으로 확인시켜도 좋다.
- 이 컬렉션으로 **스펙 310 엔티티 평가**를 걸 수 있음을 안내: 평가 문제집(kind=rag, 대상=movies-demo)에
  "RAG: 엔티티 id" 판정으로 정답을 달면 됨(예 `movie_id=101`, 조합 `director_id=9,genre_id=6`).

## 주의
- **mock-embed는 의미 아님**(결정적일 뿐) — 의미 데모는 실모델로. 컬렉션 모델은 불변이라 모델을 바꾸려면
  다른 이름의 컬렉션을 새로 만든다.
- seed 무변경. 데이터는 `movies.jsonl` 한 파일 — 영화 추가/수정은 그 파일에 행을 더하고 재적재(멱등).
