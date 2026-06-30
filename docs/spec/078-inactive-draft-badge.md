# 078 — 미활성 초안 배지로 "편집 미반영" 안내 (이슈 1)

## 배경

사용자 보고: "에이전트 수정 후 플레이그라운드에서 조회하면 바뀌지 않음."

사용자 결정(AskUserQuestion): **"미활성 배지로 안내 강화"** — draft/active 버전 로직은 유지하고,
초안이 미반영 상태임을 배지로 알린다.

## 현 배선 (실측 — 추측 금지)

- **편집은 항상 초안에 저장된다**: `update_agent`(agents.py:144-149)는 status='draft' 버전을
  생성/갱신할 뿐, 서빙 config(`Agent.config`)는 건드리지 않는다. `activate_version`(agents.py:202)이
  비로소 draft.config를 `Agent.config`로 복사한다.
- **Playground/사이드바는 활성 서빙 config를 본다**: `list_agents`(agents.py:90-93)는
  `agent_to_out`로 직렬화하며 `model/persona/temperature/...`를 모두 **`a.config`(활성 서빙)**에서 읽는다
  (serializers.py:72-87). → 초안에만 들어간 편집은 활성화 전까지 Playground에 안 보인다 = **보고된 증상**.
- **초안 존재는 클라에서 감지 가능**: `list_agents`는 `selectinload(Agent.versions)`로 draft 포함 **모든**
  버전을 직렬화한다(serializers.py:91-99). 따라서 `agent.versions.some(v => v.status === 'draft')`로
  초안 유무를 안다. Playground도 `listAgents()`로 같은 데이터를 받는다(Playground.tsx:65).
- **AgentsView는 이미 충분히 안내**한다(갭 아님): 편집 모달 부제 "변경사항은 초안 …에 저장됩니다 —
  활성화하기 전까지 현재 버전이 계속 서빙합니다"(:147), 저장 토스트 "초안에 저장됨 — 활성화하면
  게시됩니다"(:1310), 상세 드로어 초안 섹션+활성화 버튼(:1036-1087), 목록 `+초안` Tag(:1444),
  Alert "편집은 항상 초안에 저장됩니다 …"(:1152). → **남은 갭은 Playground 단독**.

## 목표 (완료 조건 — 측정 가능)

1. Playground에서 활성 에이전트에 **미활성 초안이 있으면** 헤더에 **"미반영 초안" 배지**를 표시하고,
   배지에 "Playground는 활성 버전을 실행 — Agents에서 초안을 활성화해야 반영" 취지의 툴팁을 단다.
2. **에이전트 피커(AgentCombo)**에도 초안 표식을 단다: 트리거(현재 선택)와 드롭다운 각 행에
   초안 있는 에이전트를 `초안` Tag로 구분 → 어느 에이전트가 미활성 편집을 안고 있는지 한눈에.
3. **진실원 기반**(learning 035): 배지는 mock 상수가 아니라 `agent.versions`의 실제 draft 상태로
   구동한다. 초안 없으면 배지 없음(거짓 배지 0). code/external 에이전트는 draft 상태 버전이 없으므로
   자연히 배지 없음(소스 게이트 불필요 — 실제 draft 유무로만 판정).
4. 무회귀: 초안 없는 에이전트의 Playground 표시는 기존과 동일.

## 조치 (Playground 단독 — 백엔드 변경 0)

### DebugChat.tsx
- 헬퍼 `hasDraft(a: Agent) = (a.versions ?? []).some(v => v.status === 'draft')`.
- `DraftBadge({ compact })` 컴포넌트: 금색 Tag(compact면 아이콘만) + Tooltip
  ("이 에이전트에 미활성 초안 편집이 있습니다. Playground는 활성 버전을 실행합니다 —
  변경을 반영하려면 Agents에서 초안을 활성화하세요").
- 헤더 바(~519, ExposeBadges 인근): `{hasDraft(agent) && <DraftBadge compact={compact} />}`.
  compact에서도 노출(초안 미반영 안내가 핵심이므로 아이콘만이라도 보존).
- AgentCombo 트리거(persona 줄 ~188): 초안이면 작은 `초안` Tag 인라인.
- AgentCombo 드롭다운 각 행(~274, A2A/mcp Tag 옆): `{hasDraft(a) && <Tag color="gold">초안</Tag>}`.

## 검증

- **타입**: `tsc --noEmit`(admin) 무에러.
- **브라우저**(Playwright + 시스템 Chrome): ui 에이전트에 초안을 만든 뒤(편집 저장 또는 API)
  Playground 헤더에 "미반영 초안" 배지 렌더 + AgentCombo 드롭다운에서 초안 Tag 캡처. 초안 없는
  에이전트로 전환 시 배지 사라짐(무회귀). antd 6 클래스는 learning 080 준수(Tag는 `.ant-tag` 불변).
- **거짓초록 방지**: 셀렉터가 0개면 통과 아닌 측정 실패로 다룸(learning 080·035).

## RBAC 체크리스트 적용 여부

**관련 없음** — 버전 status는 유저별/테넌트 데이터가 아니라 에이전트 버전 메타(전역). 표시 전용이며
user_id/테넌트 컬럼·소유권 헬퍼 미접촉, 유저 데이터 입구 불변.

## 완료 체크
- [x] DebugChat hasDraft 헬퍼 + DraftBadge(툴팁) 컴포넌트
- [x] 헤더 바 배지(compact 포함) + AgentCombo 트리거·드롭다운 행 초안 Tag
- [x] tsc 무에러 + 브라우저(초안 에이전트 배지 렌더 1·초안 없는 에이전트 배지 0·드롭다운 초안 Tag 1, 정리 삭제)
