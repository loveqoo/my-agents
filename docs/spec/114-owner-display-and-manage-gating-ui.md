# 114 — 화면에 주인(owner) 표시 + 비소유 관리 버튼 숨김

## 배경 / 왜

112가 카탈로그 관리(수정/삭제)를 소유자/특권으로 게이트했으나 **UI는 그대로**다 — member가 못 만지는
항목에도 수정/삭제 버튼이 보이고, 누르면 404. 소유 정보도 화면에 없다. 사용자 "1~4 루프"의 2번:
목록에 **주인을 표시**하고, **내 것 아니면 관리 버튼을 숨긴다**.

## 설계

### 백엔드가 판정을 소유(단일 술어), 프론트는 표시만 (learning 113 ④)

프론트가 소유권을 재계산하면 casbin admin 역할을 모른다(프론트는 `is_superuser`만) → **드리프트·오판**.
따라서 `can_manage`를 **백엔드가 각 Out 객체에 실어** 내려준다.

- `ownership.may_manage(row_owner, principal, enforcer) -> bool` — `assert_may_manage`의 **불리언 형제**
  (단일 술어, assert가 이걸 호출해 raise). 특권 or 소유자 본인.
- `AgentOut`·`CollectionOut`·`McpServerOut`에 `owner_id: str|None` + `can_manage: bool` 추가.
- 직렬화기는 `owner_id`만 통과(순수 유지). `can_manage`는 **list·get 라우트**에서 principal로 계산해
  세팅(표시 표면). 생성/수정 응답은 기본 `True`(행위자=소유자·방금 만든/고친 것).

### 프론트 (표시만, 프롭 스레딩 최소)

`can_manage`는 **각 item 필드**라 뷰가 이미 가진 객체에서 바로 읽는다(새 프롭 불요). `me`(AuthGate 보유)는
소유 라벨 표기용으로만 얇게 전달.

- **관리 버튼(수정/삭제/버전/발행/문서 업로드) = `item.can_manage`일 때만 렌더**. 아니면 숨김.
- **소유 라벨**(작은 Tag): `owner_id==null`→"공유" · `owner_id==me.id`→"내 것" · 그 외→"다른 사용자".
- 3뷰 공통: AgentsView·CollectionsView·BlocksView(mcp).

### 무회귀

오늘 모든 카탈로그 행은 NULL-owned + admin=superuser → `can_manage=true` 전부 → 버튼 그대로(무변화).
소유 라벨은 NULL→"공유"만 표시. member/멀티유저에서 비로소 버튼 숨김이 발동(전방 안전).

## 검증

- **백엔드 3런**: 단위(may_manage 술어=assert와 동치) + 실 DB(list/get 응답에 owner_id·can_manage:
  superuser=전부 true·member=자기/특권만 true) + (해당 없으면 codex 생략 — 순수 표시 파생, 인가 자체는
  112/113이 이미 rung3 통과. may_manage는 assert_may_manage와 동일 술어라 별도 적대 불요, 동치성만 단언).
- **프론트 브라우저**: 시드 상태에 owner 다른 항목 하나를 만들어 라벨("다른 사용자")+버튼 숨김 확인,
  NULL-owned="공유"+superuser는 버튼 보임 확인. 스샷.

## 비목표 (OUT)

- 소유권 **이전** UI(관리자가 주인 바꾸기) — 069 이전 금지 기조, 별개.
- 사용자 표시 이름 조인(owner_id→display_name) — 지금은 "다른 사용자"로 충분(이메일 노출 회피).
- 목록 owner 필터/정렬 — 필요해지면 후속.
