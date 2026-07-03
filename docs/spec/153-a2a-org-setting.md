# 153 — A2A organization 설정 (실사용 #6, 앱 설정 저장소 신설)

## 요구 (사용자 2026-07-03)
A2A 오픈할 때 organization 이름을 설정할 수 있어야 한다 — 지금은 카드에 "my-agents" 하드코딩
(a2a_server.exposed_agent_card 1곳).

## 설계
- **앱 설정 저장소 신설(범용 기반)**: `app_settings(key PK, value JSONB)` + 마이그레이션.
  후속(#7 skills 설정·#9 buddy 게이트)이 재사용할 최소 프리미티브.
- **API**: `GET /admin/settings`(전체 dict) · `PUT /admin/settings/{key}`(value) — 특권 게이트
  (스펙 150 require_model_manage와 동형: 머신·superuser·admin). **키는 닫힌 집합**(현재
  `a2a_org_name` 하나) — 미지 키 400(쓰레기 키 적치 방지), 값 검증은 키별(문자열·80자 캡·공백 거부).
- **카드 반영**: exposed_agent_card의 organization = 설정값 → 없으면 env `A2A_ORG_NAME` → 기본
  "my-agents" (3단 폴백, 무재시작 반영 — 카드 fetch 시 DB 읽기).
- **UI**: 관리자 그룹에 '설정' 메뉴 신설(SettingsView) — A2A organization 입력+저장.

## 검증 (2026-07-04 완료)
- verify_153 17/17: CRUD·미지 키 400·값 검증 4종·member 403·카드 통합(ASGI 실호출)·폴백 의미
  (미저장→env / **기본 문자열 의도 저장→env가 못 이김** / 오염 값→fail-safe)·원복.
- e2e 9/9(fast-worker): 메뉴·저장 토스트·재진입 유지·원복(curl 실측)·빈 값 경고 — K4b는
  네트워크 감시로 "PUT 미호출"까지 증명(토스트만으론 저장 안 됨이 증명 안 됨 — 서브에이전트가
  자발 보강).
- codex: Medium 1(폴백 의미 역전 — 값 비교로 미설정을 추정하면 기본 문자열 의도 저장을 뭉갬 →
  get_setting_stored로 저장 *여부* 분기)·Low 1(읽기 재검증 — DB 오염 값이 공개 카드에 노출 →
  읽기 시 validator 실패=미저장 취급) → 2건 수정. Low(카드 fetch당 DB 1쿼리)는 빈도 낮아 수용.

## 경계(정직)
- 카드 fetch마다 설정 DB 조회 1회 — 캐시 없음(빈도 낮음, 무재시작 반영이 우선).

## OUT
- 설정별 UI 자동 생성·감사 로그 — 후속. env A2A_SELF_BASE_URL은 기존 유지(배포 정체성은 env).
