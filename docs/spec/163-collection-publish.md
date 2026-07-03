# 163 — RAG 컬렉션 공개(publish) 토글

## 문제(실사용)
컬렉션 등록에 공개/비공개 설정이 없어 **남과 공유할 수 없다**. 내가 소유한(private) 컬렉션은
`agent_may_wire`(스펙 113) 게이트로 **내 에이전트만** 검색에 쓸 수 있고, 다른 사용자의 에이전트는
배선이 막힌다. 같은 "공개" 장치가 **MCP엔 이미 있지만**(`published` + `PUT /mcp-servers/{id}/publish`),
컬렉션은 `agent_may_wire(c.owner_id, False, ...)`로 **항상 비공개 하드코딩**(chat.py:305)이라 공유 길이 없다.

## 결정(사용자 확정)
**"사용만 공개"(MCP와 동일)**. 공개하면 다른 사용자의 에이전트도 이 컬렉션을 검색에 쓸 수 있다.
**수정·삭제는 여전히 소유자/특권만**(may_manage 불변). 공개=쓰게 열어주기지 남이 편집이 아니다.
소유권(private/public 태그, owner_id)과 **직교하는 별개 축**: 컬렉션은 "내 소유(private)이면서 공개됨"일 수 있다.

## 변경(MCP 선례 미러)
### 백엔드
- **models.py**: `Collection.published: Mapped[bool] = mapped_column(Boolean, default=False)`(McpServer:221 미러).
- **alembic**: `op.add_column("collections", Column("published", Boolean, nullable=False, server_default=text("false")))`.
  기존 행은 false=비공개(fail-closed, 무회귀 — 지금까지 못 쓰던 걸 열지 않음). down=drop_column.
- **chat.py:305**: `agent_may_wire(c.owner_id, c.published, wiring_owner, ...)` — 하드코딩 `False`→`c.published`.
  공개 컬렉션은 rule 4(published)로 타 작성자 에이전트에도 배선 허용.
- **schemas.py**: `CollectionOut.published: bool = False`; `CollectionPublishIn { published: bool }`.
- **serializers.py**: `collection_to_out`에 `published=c.published`.
- **rag.py**: `PUT /{cid}/publish` — `assert_may_manage`(소유자/특권만), `obj.published=body.published`, commit.
  (MCP의 external 재공개 금지 가드는 불필요 — 컬렉션엔 source 세탁 축 없음.)

### 프론트(fast-worker 위임)
- **api.ts**: `publishCollection(id, published)`. **mockData.ts**: `Collection.published?: boolean`.
- **CollectionsView.tsx**: 목록/상세에 "공개" 배지 + 토글 스위치(can_manage일 때만). OwnerTag 옆에 병렬.

## 검증
`tests/verify_163_collection_publish.py` (httpx ASGI):
1. 생성 직후 published=false → bob 에이전트가 alice 컬렉션 배선 시도 = 미해석(차단).
   (agent_may_wire 단위 or chat 해석 관측).
2. alice publish=true → bob 에이전트 배선 = 해석됨(허용).
3. bob publish 시도 = 404-fold(may_manage 아님). alice unpublish=true→false 멱등.
4. published가 소유권(can_manage)과 직교 — publish해도 bob can_manage=false 유지.

## codex 163 (게이트 커버리지 정합)
- **High(수정)**: `POST /collections/{cid}/search`가 published/소유권을 안 봐서 타인 비공개 컬렉션
  청크 본문을 직접 유출(채팅 배선 게이트를 이 엔드포인트가 우회 — installed≠covering). →
  `may_use_collection`(특권/소유자/published) 헬퍼 신설, search에 게이트(404-fold). `unpublish` 즉시
  차단도 이걸로 성립(매 요청 재평가).
- **Med(수정)**: `GET /collections/{cid}/documents`도 무게이트 — 파일명·상태 등 문서 메타 유출. 같은
  `may_use_collection`로 막음(404-fold). 컬렉션 *존재/메타*는 list/get서 전역이지만 *문서 내용·목록*은 사용-게이트.
- **세 축 정리**: 가시성(list/get=전역)·관리(may_manage=owner)·사용(may_use_collection=owner|published|특권).
  publish는 *사용* 축만 연다. 배선·직접검색·문서목록이 모두 같은 사용 술어를 통과(drift 0).

## OUT
- 공개 컬렉션 목록 필터/검색. 공개 시 인제스트 품질/PII 경고. per-user 세밀 공유(특정 사용자에게만).
  rule 4는 전체 공개(모든 로컬 작성자) — MCP와 동일 입도.
