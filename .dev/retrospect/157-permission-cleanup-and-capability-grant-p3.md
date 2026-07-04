# 157 — 죽은 권한 개념 제거 + 능력 부여 UI P3 (스펙 177 P3)

## 맥락
P1(도구 기본 승인)·P2(에이전트 오버라이드+승인자) 위에서, 모델을 "능력/역할/승인" 3개념으로 수렴한다.
잔재 정리: `config.permissions[]`(런타임 미강제)·"권한" 빌딩블록·`Permission.approver`(죽음) 전면 제거.
신규: 능력 부여 UI(member는 deny-by-default라 부여 없인 능력을 영영 못 씀 — 최대 병목).

## 한 것
- **완전 제거**: Permission 모델/CRUD/블록탭/피커, `config.permissions[]` 필드·serializer·seed·references
  축, 3개 스키마 필드. 교차절단 ~20파일(백+프론트+테스트). `permissions` 테이블 DROP 마이그레이션.
  영향 테스트는 폐기/편집(046 권한 arm 제거·MCP/에이전트 불변식 유지, 148 권한 케이스 제거, cleanup_046 삭제).
- **능력 부여**: `authz.{add,remove}_policy/get_policies` + `/admin/policies` GET·POST·DELETE. **보안 경계**
  (`_assert_grantable`): object는 `capability:*`만·와일드카드(*) 금지·action=invoke 고정 + subject 검증
  (역할명 또는 실존 유저). UsersView 부여/회수 패널. require("users","manage")로 admin 전용.

## 배운 것
- **손으로 "다음 순번"을 붙이는 마이그레이션 리비전 ID는 충돌하고, 임포트·테스트가 그걸 못 잡는다 —
  적대 검토(deep-reasoner)만 잡았다(H2건).** P2가 `a1b2c3d4e5f7`(=spec150 이미 사용), P3가
  `b2c3d4e5f6a8`(=spec151 이미 사용)를 재발급했다. 저자(나)가 ID를 "a1b2c3d4e5f6→f7", "b2c3d4e5f6a7→a8"
  식으로 손으로 증가시켰는데 그 슬롯을 앞선 스펙이 이미 썼다. **치명적 성질**: alembic은 중복 리비전을
  에러가 아니라 `warning` 후 map에서 **조용히 덮어쓴다** → 둘 중 하나가 그래프에서 사라지고(파일시스템
  순서 의존=비결정), drop이 안 돌거나 다른 마이그레이션(approver/tools_meta 컬럼)이 사라져 런타임 SQL
  오류. `import api.main`·8개 테스트 green이 이걸 전혀 못 봤다(마이그레이션은 앱 임포트 경로가 아니고,
  테스트 DB는 이미 스키마가 있어 마이그레이션을 안 돎). 봉합=고유 ID 재발급 + 체인 정정 + 파일명 일치 +
  헤더-only 그래프 검증(단일 head·고아 0). 일반화: **비가역·인프라 변경(마이그레이션·인덱스·시드)은 앱
  임포트/단위 테스트의 사각지대다 — 전용 검증(그래프 무결성·실 upgrade)과 적대 검토를 따로 걸어야 한다.**
  [[adversarial-review-before-destructive-ship]] [[verification-ladder-three-rungs]]
- **권한 부여 표면은 그 자체가 권한상승 벡터 — object를 화이트리스트 접두로 좁혀라.** 능력 부여
  엔드포인트가 admin 전용이어도, object를 자유 문자열로 두면 admin이 `(member, "users", "manage")`나
  `(member, "*", "*")`를 실수/악의로 부여해 상승이 가능하다. `capability:` 접두 + 와일드카드 금지 +
  invoke 고정으로 **이 UI의 사용역을 "능력 부여"로 봉인**했다(리소스 권한·상승은 애초에 표현 불가).
  P2의 [[gate-on-intent-value-not-mutable-baseline]] "값 자체로 판정"의 자매편 — 표면을 좁혀 위험 상태를
  표현 불가로 만든다.
- **"죽음"은 런타임 강제 여부로 판정하되, 제거 범위는 배선까지 전수 grep.** `config.permissions[]`는
  chat/runtime/broker에서 강제 0(죽음)이지만 블록타입·시드·참조가드·serializer·프론트 피커에 널리 배선.
  "런타임 미사용"과 "코드에서 미참조"는 다르다 — 후자를 전수 grep해야 이동/제거가 안 깨진다.
  [[move-breaks-references-both-directions]]
- **한 단어가 두 개념이면 제거가 위험하다("permission").** `config.permissions[]`(죽은 빌딩블록)와
  `Approval.permission`(살아있는 승인 민감도 라벨, 스펙066)이 같은 단어. grep-치환이 살아있는 쪽을
  건드릴 뻔했다. deep-reasoner가 "두 뜻 공존이 함정"이라 명시 — 제거 전 **의미 축을 분리**해 확인.

## 검증
verify_177_p3(보안경계 G1-G4·grant/revoke 라운드트립 G5-G6[실 casbin enforce 반영]·subject 검증 G7)·
verify_046(권한 arm 폐기·MCP/에이전트 불변식 유지, stale MCP 054 drift 현행화)·verify_148(40/0)·회귀
(092/171/151/177/066/041)·마이그레이션 그래프(헤더 파싱: 단일 head a177b3c4d5e6·중복0·고아0)·admin tsc·
브라우저(shot-perm-removed-177: 권한 탭 부재+능력부여 패널 렌더). **적대 검토 H2건(리비전 충돌)→봉합, L1
스테일 주석→정정, 앱 코드 제거 클린 판정.** 113/152 실패는 확증된 기존 결함(t113 이름재사용·V4 A2A, 무관).

## 스펙 177 종결
P1(기본정책)·P2(오버라이드+승인자)·P3(정리+능력부여)로 "능력/역할/승인" 3개념 수렴 완료.
잠복: 커스텀 impl(신뢰 레지스트리)이 `overrides.toolPolicy` 직접 주입 시 우회 가능하나 위협모델 밖.
