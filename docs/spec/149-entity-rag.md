# 149 — 엔티티 RAG (컬렉션 종류 축 + JSONL 행 단위 인제스트)

## 배경 (사용자 상황, 2026-07-03)
문서 RAG와 별개로 **엔티티(행) 검색용 RAG**가 필요. 사용자 환경은 테이블 6개+ 조인이라 단순
테이블 임베딩 불가 → **SELECT SQL로 JSONL을 이미 추출**하고 고정 스키마를 준비함:
`{"metadata": {각 테이블 id들…}, "data": {임베딩 소스}}` (한 줄=한 엔티티).
요구: data를 임베딩하고 metadata를 함께 저장 → 유사도 검색에서 **metadata가 같이 반환**되어
id로 원본을 특정할 수 있어야 한다.

## 설계
- **컬렉션 종류 축**: `Collection.kind = "document"(기본) | "entity"`. 생성 시 선택, 생성 후 불변
  (임베딩 모델과 동급 — 저장 형태가 다름).
- **인제스트(entity)**: 기존 업로드 엔드포인트에서 kind 분기. `.jsonl` 파일을 행 단위 파싱:
  - 각 행 = JSON 객체, `metadata`(객체)·`data`(객체 또는 문자열) 필수.
  - **1행 = 1청크, 분할 없음**(chunk_size/overlap 무시). 임베딩 텍스트 = data가 문자열이면 그대로,
    객체면 `key: value` 줄 평탄화(중첩 값은 JSON 직렬화) — 결정적.
  - `Chunk.meta`(JSONB 신설)에 metadata 원본 저장.
  - **fail-closed**: 형식 위반 행 발견 시 파일 전체 400(행 번호 명시) — 소스가 SQL 추출물이라
    위반=파이프라인 버그, 부분 스킵은 비즈니스 데이터의 조용한 유실. 행 수 캡(5,000)·행 텍스트
    캡(8,000자)도 초과 시 400(조용한 축소 금지). 파일 바이트 캡은 기존 업로드 캡 공유.
  - **JSON Schema 선택 등록**(2026-07-03 합의): `Collection.entity_schema`(JSONB, 선택) — 등록 시
    모든 행을 이 스키마로 검증(위반=행 번호와 400, 봉투 검사 위에 내용물 드리프트를 잡음 — SQL
    변경으로 id 컬럼 누락 등). 미등록이면 봉투 검사만. 추후 에이전트용 "엔티티 모양 문서" 역할.
  - 갱신 = 파일 삭제 후 재업로드(문서 관리 화면 그대로, upsert는 후속).
- **검색**: 공유 코어(`search_collections`)가 `Chunk.meta`를 함께 select → hit에 `meta` 포함.
  - `POST /collections/{cid}/search` 응답 SearchHit에 `meta` 추가(문서형은 None).
  - 인-챗 RAG 도구 포맷: entity hit이면 metadata를 함께 표기(에이전트가 id 인용 가능).
  - 검색 시험 드로어에 metadata 표시.
- **UI**: 생성 모달에 종류 Select(문서형/엔티티형 — 엔티티형이면 청킹 필드 숨김+JSONL 형식 안내),
  목록에 kind 태그, 엔티티 컬렉션 업로드 accept=.jsonl.
- 마이그레이션: `collections.kind` + `rag_chunks.meta` 2컬럼(변환 없음 — 기존=document).

## 검증 (2026-07-03 완료)
- verify_149 31/31: 파서 표본(위반 7종 행 번호)·스키마 검증·캡 3종(행 수/행 텍스트/metadata)·
  정규식 키워드 거부·스키마 제거/재등록·업로드 400(문서 행 미생성)/성공·meta 저장·검색 meta
  동반·문서형 무회귀·도구 포맷.
- e2e 7/7(fast-worker, shot-entity-rag-149.mjs): 종류 선택 시 폼 전환·엔티티 태그·JSONL 업로드
  라벨·위반 업로드 행 번호 토스트·정상 적재·검색 카드 metadata 시각 확인·삭제.
- codex 적대 리뷰: High 1(스키마 ReDoS)·Medium 4·Low 3 → 5건 수정(정규식 키워드 거부+스키마
  크기 캡·metadata 2,000자 캡·명시적 null=스키마 제거·행 캡 선검사·kind server_default 정합),
  2건 경계 기록(아래).

## OUT (후속·정직 경계)
- **DB 직결(JDBC)·API 주기 동기화·자동 컬럼 선택** — 사용자도 편리하다 본 방향이나 연결 설정·
  스키마 매핑 UI가 커서 v2. v1은 "SQL은 사용자가, 적재는 우리가".
- 메타데이터 필터 검색(`WHERE meta @> …`) — v2 (JSONB라 스키마 변경 없이 추가 가능).
- upsert/증분 갱신(키 기반) — v1은 파일 교체. 스키마 편집 UI(생성 시만 입력, 수정은 API).
- 정확 id 조회는 RAG가 아닌 도구 조합(SQL/MCP) 권장 유지(선행 논의).
- **경계(codex)**: ① meta는 본문(text)과 동일한 비신뢰 데이터로 도구 결과에 노출(인젝션 표면 —
  구조 분리·허용 키 목록은 후속) ② 평가기 `rag_source_contains`는 엔티티에서 변별력 없음(모든
  행이 같은 파일명) — 엔티티용 meta 기반 assert(`rag_meta_contains` 류)는 평가 백로그 씨앗.
- JSON Schema 정규식 제약(pattern류)은 v1 미지원(ReDoS 경계 — 명확한 400 안내).
