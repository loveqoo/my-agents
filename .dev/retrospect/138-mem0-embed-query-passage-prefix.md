# 138 — mem0 임베딩 query/passage 접두어 주입 (스펙 160)

스펙 158·159 OUT의 후속(사용자 "접두어 주입 이어서"). 비대칭 임베딩 모델(e5·arctic)이 query/passage
접두어를 요구하는데 mem0가 memory_action을 무시하고 원문 전송하던 걸, action별 접두어 주입으로 해결.

## 배운 것
- **가정을 만들면 측정부터.** "e5/arctic은 비대칭이라 접두어가 크게 도움"이라는 일반 지식으로 바로
  구현하려 했는데, 로컬 e5 실측은 **효과 미미**(분리도 +0.062→+0.063, 순위는 어차피 5/5). [[probe-deeper
  -before-concluding]]·회고 137의 "정적 기본값은 케이스마다 다름→측정" 연장. 측정이 설계를 바꿨다 —
  하드코딩 대신 **설정형(기본 no-op)**으로, 실효과가 있는 모델(배포본 arctic)만 켜게.
- **비파괴 경로를 측정으로 찾았다.** "검색만 접두어(기존 raw 저장 유지)"가 e5에서 해롭지 않음(+0.069)을
  측정 → arctic-v2.0이 query만 접두어·passage raw 설계라는 사실과 합류 → **기존 11건 재인덱싱 없이
  검색에만 접두어**가 정확한 해법. 데이터 마이그레이션 없이 배포본 개선.
- **주입은 소비 채널이 아니라 변환 입구에.** 접두어를 embed 인자에만 붙이고 mem0가 원문을 payload에
  따로 저장 → 저장/표시 텍스트엔 안 샌다(측정+codex 확인). "임베딩 입력"과 "저장 데이터"를 분리하는 게
  핵심 — 접두어는 벡터 계산에만 영향, 사용자가 보는 기억엔 무영향.
- **접두어는 래핑 시점 캡처(호출 시점 전역 읽기 아님).** 첫 구현이 `_prefix_for`에서 모듈 전역을 call-time
  읽어, 테스트가 env 복원하니 embed 때 빈값이 됐다(프로덕션은 전역 고정이라 무증상이나 설계상 부정확).
  백엔드 생성 시 접두어를 캡처하는 게 옳다 — 테스트가 이 미묘한 시점 결합을 드러냈다.
- **설정형 기본 no-op = 무회귀 + 경계 자연 문서화.** 둘 다 빈값이면 래핑 스킵. passage 접두어를 기존
  raw DB에 켜면 벡터 혼재(운영 경계, codex) — 하지만 arctic은 query-only라 이 경계를 안 밟는다.

## 검증
verify_160 9/9(no-op·search=query·add/update=passage·batch·arctic 모사 저장무변경·실 e5 왕복 의미매칭).
접두어 payload 누출 없음 측정(저장·회상 텍스트 원문 유지). codex 코드결함 0(payload분리·None없음·이중래핑
없음·provider호환 소스확인), 경계 1(passage 기존DB 혼재)=arctic query-only 비파괴로 문서화.

## OUT
- passage 접두어용 재인덱싱 도구·모델별 접두어 UI(env로 충분). 배포본 arctic 접두어 켜고 회상 품질 실측.

[embed-prefix,asymmetric-model,measure-before-assume,non-destructive-via-measurement,transform-input-not-stored-data,capture-at-wrap-not-call-time,configurable-default-noop]
