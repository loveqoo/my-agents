# 스펙 216 — 빌딩 블록 '수정일' 실제 배선

## 배경 (사용자 실사용 지적 2026-07-07)

빌딩 블록 목록의 '수정' 열이 편집해도 안 바뀐다. 원인 = 백엔드 `get_blocks`가 이 값을 실제 수정일
대신 **항상 `"—"`로 하드코딩**(blocks.py, 전 카테고리). 죽은 열(스펙 213 검색창과 동종). 사용자 결정:
**실제 수정일로 배선**.

## 편집 가능성 조사 (배선 범위 결정)

- **페르소나**: 편집 가능. DB에 `updated_at`(onupdate=func.now()) **이미 있음** → 표시만 배선.
- **MCP**: 편집 가능. `updated_at` **없음** → 컬럼 추가(마이그레이션) 후 배선.
- **메모리 타입**: 빌딩 블록에서 **읽기 전용**(BLOCK_FORMS={}, 시스템 정의 enum, spec 016) → 수정 자체가
  일어나지 않음. `updated_at` 불필요, 열은 "—" 유지(정직한 N/A).
- 임베딩: 빌딩 블록에서 탭째 숨김(스펙 036) → 무관.

## 변경

### 1. models.py — McpServer에 updated_at 추가
`updated_at: Mapped[datetime] = mapped_column(DateTime(tz=True), server_default=func.now(), onupdate=func.now())`
(Persona와 동일 패턴). onupdate는 ORM-side — update 라우트가 obj.setattr+commit이라 발화(확인함).

### 2. 마이그레이션 (신규, down_revision=f211a1b2c3d4=현 head)
`mcp_servers.updated_at` 컬럼 추가(server_default=now(), nullable=False). 기존 행은 마이그레이션 시각으로
백필(다음 편집 때 실제 갱신). onupdate는 앱-side라 DB 트리거 불요.

### 3. blocks.py — get_blocks
- persona item: `"updated": _iso(row.updated_at)` (serializers._iso 재사용)
- mcp item: `"updated": _iso(row.updated_at)`
- memory item: `"—"` 유지(읽기 전용)

### 4. 프론트 BlocksView
- `fmtTime`(admin/format.ts)으로 렌더 — ISO→친화 표기(오늘=시:분/올해=M월D일/그외=YYYY), "—"는
  파싱 불가라 그대로 통과. 열(1028)·드로어(1314) 둘 다.
- 열 제목·드로어 라벨 **"수정" → "수정일"**(편집 동작과 혼동 제거 — 사용자 최초 질문 해소).

## 완료 기준 (측정)
- 마이그레이션 후 DB에 mcp_servers.updated_at 존재. API 재기동 부팅 성공(head 단일).
- 브라우저: 페르소나 편집 → '수정일'이 방금 시각으로 갱신. 메모리 탭은 "—". MCP 편집 → 갱신.
- tsc 0.

## OUT
- 메모리 타입 updated_at(읽기 전용이라 무의미) · 임베딩(숨김) · 다른 뷰(세션 등은 이미 fmtTime 사용).
