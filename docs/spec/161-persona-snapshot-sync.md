# 161 — 페르소나 수정 반영: 스냅샷 유지 + 명시적 동기화(템플릿→인스턴스)

## 문제 (실사용 피드백)
1. 에이전트에 페르소나를 설정하고 쓰다가 **페르소나를 수정해도 에이전트에 반영 안 됨**.
2. 에이전트의 페르소나가 **현재 원본과 다른지(오래됐는지) 표시가 없음**(버전/상태 불가시).

## 근인 (확정)
에이전트는 페르소나를 **저장 시점 스냅샷으로 복사**한다: `config.persona`=이름(참조), `agent.persona`
(Text 컬럼)=`resolve_persona(name)`로 푼 **본문 복사본**(agents.py:195·235·366·410). 런타임은 이
스냅샷을 서빙(chat.py:138 `persona = agent.persona`, 이름으로 재해석 안 함). Persona 테이블엔 버전 없음.
→ 페르소나 편집(persons.body 갱신)이 에이전트 스냅샷에 안 퍼지고, 오래됨 표시도 없음.

## 설계 (복사 유지 = 영향도 격리, 사용자 동의. 반영을 명시적·가시적으로)
라이브 참조는 **기각**(공유 페르소나 수정이 운영 에이전트에 무단 전파 = 양날의 검, 사용자 지적).
스냅샷을 유지하되 **템플릿→인스턴스 동기화**로 푼다:

**백엔드**
- (A) `AgentOut.personaStale: bool`. `agent_to_out(a, persona_bodies=None)` — 라우트가 `{name: body}`
  맵을 주입하면 계산: **로컬(source∈ui/code) AND 현재 본문 존재 AND 현재 본문 != 스냅샷** → stale.
  외부/A2A·이름이 블록 아님(literal)·본문 동일 → false. list/get 라우트가 personas 1회 조회해 맵 전달.
- (B) `POST /agents/{id}/persona/refresh` — `agent.persona = resolve_persona(cfg["persona"])`로 스냅샷
  **재해석(in-place)**. 이름 불변이라 새 버전 안 만듦(활성화 재해석 경로 재사용). **can_manage 게이트**
  (스펙 112/114 — 소유자/어드민만). 반환 AgentOut.
- (C) `GET /personas/{id}/agents` — 이 페르소나를 쓰는 에이전트 목록 + 각 stale 플래그(페르소나 편집
  화면의 "N개 사용·M개 오래됨"용). agents_referencing/직접 쿼리.
- (D) `POST /personas/{id}/apply {agentIds}` — 선택 에이전트 스냅샷 일괄 refresh. **각 에이전트
  can_manage 게이트**(관리 불가 대상은 건너뛰고 결과에 명시 — 남의 에이전트 무단 변경 금지, codex 축).

**프론트**
- (E) 에이전트 편집 폼: personaStale이면 **"원본 페르소나 수정됨 — 이전 내용 사용 중"** 배지 +
  **"최신 페르소나로 갱신"** 버튼 → (B) → 리로드. (두 번째 불만 = 오래됨 가시화로 해소)
- (F) 페르소나 편집(BlocksView): 저장 후 (C)로 사용 에이전트+stale 표시, 체크박스 + **"선택 반영"** →
  (D). 고친 그 자리에서 누구에게 밀지 통제(전체 자동 아님 = 격리 유지).

## 검증
- verify_161: 페르소나 쓰는 에이전트 생성→페르소나 편집→personaStale=true·systemPrompt(스냅샷) 옛 본문
  유지. refresh→스냅샷 갱신·stale=false. 외부 에이전트 stale=false. can_manage 없는 주체 refresh/apply
  거부(403/skip). 일괄 apply가 관리 가능 대상만 갱신. 무회귀: 미편집 에이전트 stale=false.
- fast-worker 브라우저 e2e(배지·갱신·페르소나쪽 반영). codex 여집합(권한·이름 literal·rename 상호작용).

## 경계 (codex 161)
- **가시성(High, 수정됨)**: `/personas/{id}/agents`도 `may_use_agent` 필터 — 타인 private 에이전트
  식별자·stale 누출 차단(스펙 147과 동일 게이트). apply 쓰기는 이미 per-agent may_manage 게이트.
- **동시성(Med, 요청-시점 반영)**: apply/refresh는 **요청 시점에 읽은 페르소나 본문**을 스냅샷에 쓴다.
  그 사이 페르소나가 또 수정되면 응답은 applied지만 다음 로드에서 다시 stale로 표시된다(재반영하면 됨).
  락은 두지 않음 — 페르소나 편집은 드물고 stale 재표시가 정직한 신호. "최신 본문 원자 보장"은 OUT.

## OUT
- 페르소나 버전/롤백(스냅샷+가시화로 당면 불만 해소, 버전은 후속). refresh를 새 에이전트 버전으로
  감사기록(현재 in-place). apply 원자적 최신본문 보장(row lock) — 요청-시점 반영으로 충분.
