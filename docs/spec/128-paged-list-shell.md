# 128 — PagedListShell: 페이지 목록 패턴 일반화 (세션·컬렉션 문서·메모리)

## 배경 / 왜
사용자: "이 패턴(127)을 세션·컬렉션 화면에도 일반화합시다." 127 `PagedMemoryList`에는 재사용 엔진
(디바운스 서버검색·페이지네이션·total 상시·지속 오류·reqSeq stale 가드)과 메모리 고유(인라인 편집·
미구성 Alert)가 섞여 있다 — 엔진을 공용 셸로 추출해 세 소비자가 공유한다(126 본문추출+얇은래퍼 동형).

### 조사로 확정 (deep-reasoner, 파일:라인 근거)
- **세션**: 백엔드 페이지네이션 완성(sessions.py LIMIT/OFFSET+count+ilike) — **프론트만 이관**.
  고유 요소=status Radio+counts 배지·행클릭 상세 Drawer·컬럼 6종. 행 삭제 없음(end 버튼은 비배선 목업).
  **덤**: 현재 사라지는 토스트 오류 → 셸의 지속 오류로 교정(learning 125 정직성).
- **컬렉션**: 목록 자체는 수동 생성 소수 — 페이지네이션 과설계(OUT). **증가 축은 컬렉션 내 문서 목록**
  (listDocuments 전량 반환) → 백엔드 페이지 API 추가(세션 쿼리와 100% 동형: SQLAlchemy LIMIT/OFFSET+
  count+filename ilike). 응답형 {items,total}로 변경(breaking — 소비처 전수 grep 후 동시 수정).
- **메모리**: PagedMemoryList를 셸 소비자로 재작성(두 벌 엔진=드리프트 방지). 인라인 편집은 columns를
  함수형(ctl 접근)으로.

## 설계

### 공용 셸 `PagedListShell<T, X>` (admin/src/admin/views/PagedListShell.tsx)
- 엔진(127에서 이동): search/q 디바운스 300ms(확정 시 page=1)·page/rows/total/loading·reqSeq stale
  가드·scopeKey 전환 시 전체 리셋·refreshKey 재조회·지속 오류 Alert·total 상시 줄·DataTable+
  조건부 Pagination(total>pageSize).
- props: `fetchPage(q,limit,offset) → {items,total,enabled?,extra?}`(enabled 기본 true — 세션·문서는
  무시, extra=도메인 확장(세션 counts)) · `columns: Column<T>[] | ((ctl)=>Column<T>[])`(함수형=메모리
  인라인 편집이 ctl.reload/setPage/rowCount 사용) · `onRowClick` · `leftSlot`(Radio/Segmented — 상태는
  소비자 소유) · `onExtra(extra)`(counts 배지 갱신) · `countLabel` · `emptyText` · `disabledAlert`
  (enabled=false 전용) · `pageSize`(기본 20) · `searchPlaceholder`.
- **검색어 보존 리셋 분리**: `scopeKey` 변경=전체 리셋(검색어 포함), **`pageResetKey` 변경=page만 1로**
  (검색어 보존) — 세션의 "status 필터 전환 시 검색어 유지" 기존 UX 보존(조사 트레이드오프 반영).

### 소비자 적용
1. **세션(SessionsView)**: 셸 이관 — leftSlot=status Radio(+counts 배지, onExtra로 수신), fetchPage=
   listSessions(filter 클로저 캡처), filter 변경 시 pageResetKey++. Drawer·컬럼·메시지 fetch 잔류.
   백엔드 무변경. 보존 체크리스트: Radio+counts·서버검색·행클릭 Drawer·컬럼 6종·필터 전환 page=1
   (검색어 보존)·모바일 카드.
2. **컬렉션 문서(DocsDrawer)**: 백엔드 `GET /collections/{cid}/documents?q&limit&offset →
   {items,total}`(세션 동형, filename ilike 이스케이프). api.ts listDocuments 시그니처 변경 —
   소비처 전수 grep 후 동시 수정. 드로어 폭 고려 pageSize=10. 업로드/삭제 후 refreshKey/reload.
3. **메모리(PagedMemoryList)**: 셸 소비자로 축소 — 엔진 삭제, columns 함수형(편집/삭제가 ctl 사용,
   "마지막 항목 삭제→이전 페이지"는 ctl.rowCount+setPage로), disabledAlert·scopeLabel 유지.
   UserMemoryPanel/AgentMemoryPanel 표면 무변경.

### 소유권/보안
- 신규 백엔드는 문서 페이지 하나 — 기존 list_documents와 동일한 읽기-개방 모델 미러(존재 확인만,
  RBAC 무변경 = 회귀 없음). 검색어는 파라미터 바인딩+like 이스케이프(세션 `_like_escape` 재사용).

## 검증
- 백엔드: verify_128 — 문서 페이지(총계·경계·ilike 이스케이프·빈 컬렉션) + 세션 무회귀(기존 verify).
- 프론트: tsc(제네릭 extra 흐름 확인) + 브라우저 3면 — 세션(필터 counts·페이지·검색어 보존 리셋),
  문서(페이지·검색), 메모리(127 shot 재실행 = 셸 재작성 무회귀).
- codex 적대: 셸 추출이 동작 바꿨나(reqSeq·리셋 시맨틱)·문서 API breaking 누락 소비처·이스케이프.

## 비목표 (OUT)
- 컬렉션 **목록** 페이지네이션(수동 생성 소수 — 증가 확인되면 후속, 세션 동형 추가 용이).
- 세션 행 삭제/end 배선(현재도 목업 — 별도 스펙).
- keyset 페이지네이션(127 OUT 승계).
