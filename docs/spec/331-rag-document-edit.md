# 331 — RAG 문서 런타임 수정(에디터 + 부분 재임베딩)

## 배경 / 요구 (사용자, 2026-07-14)

- RAG 문서를 **런타임에 수정**하고 싶다. 문서형 컬렉션만(엔티티 제외).
- 수정하면 **해당 영역을 다시 임베딩**한다.
- 에디터는 **문법 지원** — 마크다운 한정이 아니라 텍스트 형식 전부, **확장자를 인식해 하이라이트**.
- (결정) PDF는 편집 제외 — 추출 평문 편집은 원본과 어긋남. 텍스트(UTF-8) 문서만.

## 설계

### 시임: 스펙 312의 blob 재인덱싱 기계를 문서 1건으로
`document_blobs`가 원본을 보존하므로 **편집 = blob 교체 → 그 문서만 재청킹·재임베딩**.
스왑은 한 트랜잭션(구 청크 delete + 신 청크 insert + doc/blob 갱신) — MVCC라 검색 무중단(313 승계).

### "해당 영역만" 재임베딩 = 변경 청크만
재청킹은 결정적(같은 텍스트→같은 청크). 기존 청크의 `text→embedding` 맵을 만들고, 새 청크 중
**텍스트가 동일한 것은 기존 벡터 재사용**, 달라진 것만 `_embed_chunks`로 임베딩. 수정 지점
주변(경계 밀림 포함)만 비용 발생 — 사용자의 "해당 영역" 의도를 청크 입도로 정직 구현.
응답에 `{chunks, reembedded, reused}` 통계를 실어 UI 토스트로 노출(관측 우선).

### API (rag.py)
- `GET /collections/{cid}/documents/{doc_id}/content` → `{filename, text, editable}` — blob UTF-8
  디코드. PDF/디코드 불가면 `editable=false`+text 없음(400 아님 — 조회는 허용, 편집만 차단).
- `PUT /collections/{cid}/documents/{doc_id}/content` `{text}` → 갱신+부분 재임베딩, 통계 반환.
- `list_documents`의 `DocumentOut`에 `editable` 필드 추가(UI가 버튼 활성/비활성 판단).

### 소유권/입구 (RBAC 체크리스트 — collections는 owner_id 자원)
- 입구는 위 GET/PUT 2개(닫힌 집합). 둘 다 **delete_document와 동일 게이트 미러**:
  404 fold(doc 없음/컬렉션 불일치) → `assert_may_manage(col, principal)`(소유자/특권) →
  `_reject_if_reindexing`(재인덱싱 중 409, 312 F3 미러). GET도 may_manage — 원문 열람은 편집
  권한과 동급(비소유 404, 존재 비노출).
- 쓰기 가드: kind=document만(엔티티 400) · PDF 400 · 빈 텍스트 400(IngestError 미러) ·
  차원 검증은 `_embed_chunks` 기존 가드 승계.
- 편집 vs 편집 동시성: 단일 사용자 admin 도구라 last-write-wins(정직 경계로 주석 명시, OUT).

### 프론트 (admin)
- 의존성 추가: `@uiw/react-codemirror` + `@codemirror/language-data`(확장자→언어 lazy 매칭,
  md/py/js/json/yaml/html 등 광범위). antd 대응물 없음 — admin CLAUDE.md 예외 규정에 등재.
- 컬렉션 상세 문서 목록 행에 "편집" 버튼: editable=false(PDF)면 비활성+사유 툴팁.
- 에디터는 **전체화면 Modal(90vw — 192 선례)**: CodeMirror(확장자 하이라이트·다크모드 antd 테마
  연동) + 저장/취소. 저장 성공 토스트에 "청크 n·재임베딩 k·재사용 m" 통계.
- 저장 카피는 긍정문(재임베딩이 일어남을 알리되 "무엇이 되는가"로).

## 검증 (완료 조건)

1. verify_331(일회용 DB): G1 content 왕복 · G2 PDF PUT 400/GET editable=false · G3 엔티티 컬렉션
   400 · G4 **부분 재임베딩 실측**(수정 안 된 청크 벡터 동일성 유지+변경 청크만 새 벡터·통계 일치)
   · G5 재인덱싱 중 409 · G6 빈 텍스트 400 · G7 수정 내용이 검색에 반영(mock 임베딩 왕복) ·
   G8 비소유 404(존재 비노출)·chunk_count/byte_size/blob 정합.
2. 브라우저 e2e(기능): 문서 편집 → 저장 → 검색 시험에서 수정 문구 히트(외형 아닌 실효과).
3. `make lint format-check typecheck` · admin tsc/build 클린 · 기존 verify(312 계열) 무회귀.
4. codex 적대(소유권 입구·재인덱싱 경합·부분 재임베딩 여집합) P1/P2 0.

## OUT

- ~~엔티티 컬렉션 행 편집~~ → **스펙 332에서 개방**(2026-07-14) · PDF 텍스트 전환 편집 · 동시 편집 충돌 감지(낙관 잠금)
- 마크다운 미리보기 패널(요구는 하이라이트 — 필요 시 후속) · 문서 이름 변경/신규 텍스트 문서 작성
- 전역 요청 body-size 미들웨어(chunked 전송의 선검사 우회 — 인증 admin 표면이라 수용, 주석 명시)

## 결과 (2026-07-14 실행)

- 설계대로 구현 + codex 적대 P1 1·P2 2·P3 1 전부 수정:
  - **P1 집계 드리프트**: 컬렉션 chunk_count 증분을 임베딩 전 스냅샷(doc.chunk_count — expire_on_
    commit=False라 stale)이 아니라 **스왑 트랜잭션 안의 delete rowcount(실측)**로 계산.
  - **P2 통계 불변식**: 중복 신규 청크에서 reused+reembedded==chunks가 깨지던 것 → 통계는
    occurrence 기준·임베딩 호출만 유일화(축 분리).
  - **P2 크기 상한**: 파싱 후 len 검사는 이미 메모리에 올라온 뒤 — Content-Length 선검사 의존성
    추가(chunked 우회는 정직 경계 주석+OUT).
  - **P3**: 에디터 원본 ref 미초기화로 stale dirty 닫기 확인 오발 → 로드 시작 시 초기화.
- e2e 과정 발견 2건: **antd v6 Drawer DOM 클래스가 content→section**(셀렉터 드리프트) ·
  `maskClosable` v6 deprecated → `mask.closable`(admin 규칙 준수) · 새 컴포넌트는 레포 관용구
  (정적 message)를 따라야 토스트가 실제로 뜸(App.useApp()는 프로바이더 부재 시 조용히 무동작).
- 검증: VERIFY331_OK 19/19(부분 재임베딩은 embed_texts 캡처로 실증 — 결정적 mock이라 벡터 비교는
  증명력 0) · VERIFY331_UI_OK(편집→저장→"재임베딩 1·재사용 1" 토스트→검색 최상위 반영, 실모델 e5) ·
  312/313/329 무회귀(312의 1건 실패는 stash 확증 기존 드리프트) · lint/mypy/tsc/build 클린.
