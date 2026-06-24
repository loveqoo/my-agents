# 021 — Playground userId UX: 헤더 레이아웃 정리 + 과거 userId 선택

상태: **초안 (AI 작성 — 인간 검토·승인 대기)**
날짜: 2026-06-24
브랜치: `feat/agent-service` — **main 머지·push 금지**(사용자가 직접 브랜치 테스트)
지배 스펙: [007-real-agent-service](007-real-agent-service.md)(Playground/Debug Console), [020-mem0-multi-scope-and-catalog-realign](020-mem0-multi-scope-and-catalog-realign.md)(userId=mem0 user_id 축)
연관 코드: `admin/src/playground/DebugChat.tsx`(헤더), `Playground.tsx`(userId 상태/흐름), `admin/src/api.ts`; `packages/api/src/api/chat.py`(세션 생성·`_persist`), `sessions.py`(목록 엔드포인트), `models.py`(Session), 새 alembic 마이그레이션

---

## 배경 — 문제 2가지 (사용자 브라우저 테스트에서 발견)

Playground 헤더의 userId 입력에 대해:
1. **UI가 깨짐.** 입력 폭이 좁아(`width:168`) placeholder `userId (선택)`가 `userId (선...`으로 잘리고, AgentCombo·A2A 배지·버튼 2개와 한 줄에 끼어 답답하다(`DebugChat.tsx:256-290`).
2. **과거 userId를 선택하고 싶다.** 매번 손으로 타이핑하는 게 불편 — 그동안 대화했던 userId 목록에서 고를 수 있어야.

### 현재 상태에서 확인된 제약
- **userId는 DB 어디에도 저장되지 않는다.** `chat.py`는 `body.userId`를 mem0 `user_id` 축에만 태깅(`chat.py:266`). `sessions`/`messages` 테이블에 user_id 컬럼 없음. → 과거 목록을 끌어올 출처가 없음.
- 결정(사용자 승인): **세션에 userId 영속**을 출처로 한다. localStorage(기기 한정)·mem0 스토어 직접 조회(내부 결합)는 기각.

---

## 설계

### 데이터 모델 — 세션에 userId 기록
- `sessions` 테이블에 `user_id VARCHAR(80) NULL` 컬럼 추가(인덱스 — distinct 조회용).
- `chat.py`의 턴 영속 시점(`_persist`)에서 **non-empty userId가 오면 세션에 기록**한다. 빈 값이면 덮어쓰지 않음(마지막 알려진 값 보존).
- 로컬·원격(코드 에이전트) 양 경로 모두 `_persist`를 거치므로, `_persist`에 `user_id` 인자를 추가해 두 호출에서 전달.

#### 받아들이는 한계 (사용자와 합의)
세션당 컬럼 1개라 한 세션에서 userId를 도중에 바꾸면 **마지막 non-empty 값만** 남는다. distinct **목록 생성**(이번 목적)엔 충분. "세션별 정확한 userId 이력"이 필요해지면 메시지 단위 기록으로 후속 확장(이번 범위 밖).

### 엔드포인트 — distinct userId 목록
- `GET /sessions/users` → `list[str]` (non-null `user_id` distinct, 최근 사용순 정렬: `max(last_activity)` desc).
- `sessions.py`에 추가, 기존 라우터(`prefix="/sessions"`, 인증 `_auth` 적용)에 자연 편입.

### 프론트 — 헤더 레이아웃 + AutoComplete
- `admin/src/api.ts`: `listUserIds = () => j<string[]>('/sessions/users')`.
- `Playground.tsx`: 마운트 시 1회 로드해 `userIds` 상태로 보관, `DebugChat`에 prop으로 전달. 채팅 후 새 userId가 생기면 로컬 상태에 낙관적 추가(목록 신선도).
- `DebugChat.tsx` 헤더:
  - `Input` → **`AutoComplete`**(antd 6). 자유 입력 유지 + `options`로 과거 userId 제시, `allowClear`, `filterOption`(부분일치). placeholder는 짧게(`예: alice`) — 잘림 방지.
  - **레이아웃 정리**: 입력이 잘리지 않도록 폭 확보(desktop `min-width` 확대 + 필요 시 줄바꿈 허용 또는 우측 버튼군과 시각적 그룹 분리). 모바일은 기존 축소 규칙([[018-antd-mobile-responsive-playbook]]) 유지. "깨짐"의 정의 = placeholder 잘림·컨트롤 겹침 없음 + 정렬 일관.

### 진행 중 userId 잠금 (mid-conversation lock) — 추가 결정(사용자 승인)
한 세션 도중 userId가 바뀌면 mem0 스코프가 섞인다(020: `run_id` 회상은 user_id와 무관하게 그 세션의 모든 턴을 돌려줌 → recall bleed). 또한 위 "받아들이는 한계"대로 세션 컬럼은 마지막 non-empty 값만 남아 이력이 뭉개진다. 그래서:
- **진행 중인 대화(활성 에이전트의 메시지 ≥ 1)에서는 userId 입력을 `disabled`로 잠근다.** 도중 변경 자체를 막아 스코프 혼선을 원천 차단.
- userId를 다시 바꾸려면 헤더의 **"새 대화"** 버튼으로 활성 에이전트의 대화·세션을 초기화(`convos[activeId]=[]`, `sessions[activeId]` 삭제, 진행 스트림 중단)한다. **userId 값 자체는 유지** — 살짝 고쳐 다시 시작하기 쉽도록.
- 에이전트 전환(`switchAgent`)은 그대로 — userId는 에이전트 간 공유 상태라 전환만으로 바뀌지 않음(건드릴 필요 없음).
- 잠긴 입력에는 Tooltip으로 사유·해제법 안내. antd Tooltip은 disabled 엘리먼트에서 hover가 안 잡혀 `<span>`으로 감싸 트리거를 살린다.
- 구현: `userIdLocked: boolean`(=메시지 ≥ 1)와 `onResetConversation` prop을 `Playground` → `DebugChat` → `ChatHeader`로 전달.

---

## 변경 계획 (파일별)

A. **DB/백엔드**
- `models.py`: `Session.user_id: Mapped[str | None] = mapped_column(String(80), index=True, default=None)`.
- alembic 마이그레이션(신규, `down_revision='c1d2e3f4a5b6'`): `add_column sessions.user_id` + index. downgrade는 drop.
- `chat.py`: `_persist(..., user_id: str | None)` 인자 추가 — non-empty면 `sess.user_id = user_id`. 로컬·원격 두 호출에서 `body.userId` 전달.
- `sessions.py`: `GET /sessions/users` 추가(distinct, 최근순).

B. **프론트**
- `api.ts`: `listUserIds`.
- `Playground.tsx`: `userIds` 상태 로드·전달·낙관적 갱신.
- `DebugChat.tsx`: `Input`→`AutoComplete` + 헤더 레이아웃 정리. `ChatHeader` props에 `userIds`, (필요시) 옵션 타입.

C. **검증 자산**
- 백엔드: distinct/최근순/빈값 무시 로직 단위 검증(인프라 불요 페이크 or 라이브 dry-run).
- 프론트: `tsc --noEmit` + 화면 확인(사용자 브라우저 — 깨짐 해소·선택 동작).

---

## 완료 조건 (Verification)
1. 헤더에서 placeholder 잘림·컨트롤 겹침 없음, 데스크톱/모바일 모두 정렬 일관.
2. userId AutoComplete: 자유 입력 가능 + 과거 userId가 드롭다운에 뜨고 선택되면 입력에 반영.
3. 채팅하면 해당 userId가 세션에 기록되고, 다음 로드 시 목록에 나타남(교차 세션·인스턴스 공유 — DB 출처).
4. 빈 userId로 대화해도 세션의 기존 user_id를 지우지 않음.
5. 마이그레이션 up/down 클린(기존 데이터 보존). 기존 세션(user_id NULL)은 목록에서 제외.
6. **타자 검증**(서브에이전트·codex) — 누출·정합성·엣지(중복·정렬·인증) 점검. 자가검증 지양.

## 범위 밖
- 메시지 단위 userId 이력, userId 기반 권한/인증(테스트용 식별자일 뿐), userId 삭제·머지 관리 UI, agent_id 메모리(020 후속).
