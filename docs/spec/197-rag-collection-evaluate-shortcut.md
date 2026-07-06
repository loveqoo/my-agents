# 197 — RAG 컬렉션에서 '평가하기' 단축 진입

## 배경 (실사용 제안)
RAG 컬렉션 상세(문서 업로드가 있는 드로어)에서 **평가로 바로 진입**하는 단축 버튼이 없다 — 평가하려면
평가 메뉴로 가서 새 문제집을 만들고 컬렉션을 다시 고르는 왕복이 필요하다.

## 사용자 결정 (2026-07-06)
- '평가하기' → **평가 화면으로 이동 + 이 컬렉션이 프리필된 '새 문제집' 창 열기**(이름만 입력). 문제
  자동생성은 **안 함**(스펙 195 정책과 일관 — 빈 문제집, 이후 'AI 출제'/직접 추가).

## 설계 (Playground `initialAgentId` 패턴 재사용 — 순수 프론트 배선)
- **AdminShell**: `evalCollectionId` 상태 추가 → `<EvalView initialCollectionId={evalCollectionId}
  onConsumedInitial={()=>setEvalCollectionId(null)} />`. `<CollectionsView onEvaluate={(cid)=>{
  setEvalCollectionId(cid); setView('eval') }} />`. (debug/Playground의 `initialAgentId`+
  `onConsumedInitial`과 동형.)
- **CollectionsView / DocsDrawer**: 컬렉션 상세 드로어에 **'평가하기' 버튼**(문서 업로드 근처) →
  `onEvaluate(collection.id)`. can_manage 무관 노출(평가는 자기 문제집 생성 — 읽기 권한만 있으면 가능).
- **EvalView**: `initialCollectionId` prop → 마운트/변경 시 있으면 **'새 문제집' 모달 자동 열기**
  (`creating=true` · `newKind='rag'` · `newColl=initialCollectionId` 프리필) 후 `onConsumedInitial()`로
  1회 소비(재열림 방지). 기존 모달 UI 재사용(스펙 193 컬렉션 Select 프리필).

## 후속 (2026-07-06, 사용자 스샷 피드백)
- **버튼 위치**: 콘텐츠 최상단(문서 업로드 버튼 위)이 위계상 어색 → **드로어 헤더 우측(제목 반대편,
  antd Drawer `extra`)** 액션으로 이동. 라벨 '이 컬렉션 평가하기'→'평가하기'.
- **문서 0개 비활성**: `collection.doc_count === 0`이면 버튼 비활성 + 사유 툴팁("문서를 먼저 업로드하면
  평가할 수 있습니다") — 검색 근거가 없는 컬렉션은 평가 무의미.
- **'문서' 버튼 중복 제거**: 컬렉션 목록 액션 컬럼의 '문서' 버튼은 **행 클릭(onRowClick=setDocsFor)**과
  같은 동작이라 중복 → 제거(진입점 하나로).

## 검증
- **e2e**: 컬렉션 상세 열기 → '평가하기' → 평가 화면 전환 + 새 문제집 모달이 rag·해당 컬렉션 프리필 상태로
  열림 → 이름 넣고 생성 → rag 문제집(collection_id 고정) 생성 확인. 무회귀 196(목록).
- **무회귀**: tsc0 · 평가/컬렉션 기존 e2e.

## RBAC 경계 (트리거 판정)
- **비트리거**: 순수 프론트 네비게이션 + 기존 모달 프리필. 문제집 생성은 기존 `create_dataset`(owner 스탬프·
  409 중복)를 그대로 탄다. 컬렉션 읽기 권한과 무관(평가는 **자기** 문제집 생성 — 남의 컬렉션이라도 공개
  읽기 가능하면 그 컬렉션 대상 평가 가능, 기존 rag 평가 정책 그대로). 새 쓰기 입구 0.

## 경계
- '평가하기'는 모든 컬렉션 종류에 노출(문서·엔티티) — rag 평가는 search_collections 경유라 동일.
- 즉시 생성(옵션 B)은 미채택(빈 문제집 남발 방지, 사용자 결정).
