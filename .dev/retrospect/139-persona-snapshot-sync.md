# 139 — 페르소나 수정 반영: 스냅샷 유지 + 명시적 동기화 (스펙 161)

실사용 피드백: 페르소나를 수정해도 이미 쓰는 에이전트에 반영 안 됨 + 오래됐는지 표시 없음.

## 근인
에이전트는 페르소나를 **저장 시점 스냅샷으로 복사**(`agent.persona` Text 컬럼 = resolve_persona(name)),
런타임은 이 스냅샷 서빙(chat.py:138). config.persona=이름(참조)이지만 런타임은 이름을 재해석 안 함.
Persona 테이블엔 버전 없음. → 편집이 스냅샷에 안 퍼지고 오래됨 표시도 없음.

## 배운 것
- **사용자의 설계 반론이 방향을 뒤집었다(좋게).** 내 첫 권장은 "라이브 참조"(수정 즉시 반영). 사용자가
  "복사는 영향도 격리라 좋다, 문제는 반영 흐름"이라 지적 → 라이브 기각, **스냅샷 유지 + 명시적·통제된
  전파**로 재설계. 편의(자동 전파)보다 격리(무단 파급 방지)를 택한 사용자 판단이 옳았다. 초기 권장을
  고수 말고 사용자의 트레이드오프 통찰을 설계 축으로.
- **"템플릿→인스턴스" 패턴**: 스냅샷=인스턴스, 원본=템플릿. 동기화는 자동 아니라 (1)오래됨 가시화
  (personaStale) + (2)명시적 반영(refresh 에이전트쪽·apply 페르소나쪽). 두 번째 불만(버전 안 보임)도
  오래됨 배지로 해소 — 버전 시스템 도입 없이(과한 금칠 회피).
- **파생 조회 라우트도 가시성 게이트 상속(codex High)**. `/personas/{id}/agents`가 may_use_agent 없이
  전체 반환 → 타인 private 에이전트 식별자·stale 누출. list/get/chat이 막는 걸 새 라우트가 뚫었다.
  **에이전트를 반환하는 모든 새 경로는 may_use_agent 필터를 물어야**(스펙 147). 게다가 내 verify가
  그 누출을 초록으로 고정하고 있었다 — 자가 테스트가 결함을 정상으로 못박는 함정([[installed-guard-isnt-covering-guard]] 계열).
- **쓰기 게이트는 per-리소스**: apply는 페르소나 id만 있으면 호출되지만 실제 쓰기는 대상 에이전트별
  may_manage AND 참조 확인 AND source 로컬 셋이 다 참일 때만 — 남의 에이전트 무단 변경 차단(codex 비문제 확인).
- **동시성 경계는 정직하게 문서화**(codex Med): apply/refresh는 요청 시점 본문 반영. 그 사이 재수정되면
  다음 로드에서 다시 stale(재반영하면 됨). 락 안 둠 — 드물고 stale 재표시가 정직 신호. "원자 최신본문"은 OUT.
- **위임 분담**: 백엔드(로직·권한, 핀 필요) 메인이·프론트(뷰 배선, 기계적) fast-worker. fast-worker가
  "저장이 드로어 닫음→저장 직후 재로드 무의미, 대신 열 때 재로드" 모호점을 추측 말고 보고 — 지시대로.

## 검증
verify_161 22/22(생성직후 stale=false·수정→stale=true 격리·refresh/apply 갱신·404-fold·usage 가시성
필터·apply per-agent 게이트·literal 무stale). codex High(누출)→may_use_agent 필터+테스트 교정, Med(TOCTOU)
경계 문서화, 권한 우회 비문제 확인. 프론트 tsc 0·브라우저 스모크(배지·사용목록·반영버튼 렌더·콘솔에러 0).

## OUT
- 페르소나 버전/롤백. 저장 후 드로어 유지하며 즉시 stale 표시(현재 재오픈 시 갱신). apply 원자 최신본문(락).
- antd6 Alert message→title deprecated 경고(앱 전역, 범위 밖).

[persona-snapshot,template-instance-sync,user-tradeoff-reshapes-design,isolation-over-auto-propagation,derived-route-inherits-visibility-gate,self-test-locks-in-leak,per-resource-write-gate,request-time-boundary]
