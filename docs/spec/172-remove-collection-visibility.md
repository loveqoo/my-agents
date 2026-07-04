# 172 — RAG 컬렉션에서 공개/비공개(published) 개념 제거 → 전부 공용

## 배경 (사용자 교정)
스펙 163이 컬렉션에 **공개 토글(published)**을 추가했다 — 구남님 원 의도는 "public/private를 *수정
가능*하게"였는데, 구현이 **공개/비공개 상태를 새로 추가**하는 방향으로 어긋났다. 구남님 결정(2026-07-04):
**public/private·공개/비공개 개념을 RAG에서 완전히 제외**하고, 컬렉션은 **로그인한 누구나 검색에
사용**(수정·삭제는 소유자만 유지). 즉 163의 사용-공개 축을 걷어내고 "사용=전부 공용"으로 단순화.

## 접근 모델 (확정)
- **사용(검색·문서 목록)**: 로그인한 누구나(current_principal=401 익명 차단). 컬렉션은 공용 자원.
- **관리(수정·삭제·인제스트·문서 삭제)**: 소유자/특권만(assert_may_manage) — **그대로 유지, 안 건드림**.
- **목록**: 이미 전역(모두가 봄) — 유지.
- 가시성/공개 상태 축 자체가 사라짐(토글·태그·엔드포인트·컬럼 제거).

## 딜리버러블
**백엔드**
1. `models.py` — `Collection.published` 제거. 마이그레이션 drop(down_revision e5f6a7b8c9d1).
2. `ownership.py` — `may_use_collection` 제거(사용이 전부 공용이라 게이트 불요). `agent_may_wire`는 MCP가
   쓰므로 유지(rule 4 published는 MCP용으로 잔존).
3. `rag.py` — search·documents의 `may_use_collection` 게이트 제거(존재 404는 유지). `PUT /publish`
   엔드포인트·`CollectionPublishIn` import 제거.
4. `chat.py` — rag 배선의 `agent_may_wire(c.owner_id, c.published, ...)` 게이트 제거(전부 공용이라 항상
   배선; c.published 참조도 사라져야 함). embedding 완전성 검사는 유지.
5. `schemas.py` — `CollectionOut.published`·`CollectionPublishIn` 제거. `serializers.py` — published 제거.

**프론트**
6. `CollectionsView.tsx` — publish 스위치·"공개" 태그·togglePublish·publishCollection import 제거.
   **+ `OwnerTag`(public/private 라벨, 스펙 147) 제거** — 육안 확인서 발견: 구남님 "public/private,
   공개/비공개 제외"는 163 토글뿐 아니라 이 소유 라벨(public/private)도 대상. RAG 뷰에서만 제거(공유
   컴포넌트라 다른 뷰는 유지). 관리 권한(can_manage=편집/삭제 노출) 로직은 그대로.
7. `api.ts` — `publishCollection`·`Collection.published` 제거.

## 검증
- 단위/통합: 비소유 로그인 유저가 남의 컬렉션 search·documents 200(개방)·wire 성공. update·delete·
  ingest·delete-doc는 비소유 시 여전히 404(관리 소유자 유지). 익명은 401.
- 마이그레이션 drop 적용(컬럼 사라짐). UI에 공개 토글·태그 없음(브라우저 캡).
- 적대 재검토(deep-reasoner): 개방이 **사용에 한정**되고 관리로 새지 않는지(update/delete/ingest 소유자
  유지)·익명 차단·다른 불변식 무접촉 확인. 자가검증 지양.

## OUT
- MCP published(McpServer)는 그대로(별개 축). 컬렉션 목록 전역 가시성(이미 그러함). 향후 "수정 가능한
  속성"이 필요하면 별도 스펙(이번은 제거).
