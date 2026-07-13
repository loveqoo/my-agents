# 327 — 하드코딩 에이전트 정리: 코드 정의 impl은 SDK 부류로, 데모는 범용형으로

## 배경 / 동기

사용자 관찰(2026-07-13): `_bootstrap_builtins`에 하드코딩 impl 8종 — "이미 다양한 유형(범용형)이
있으니 하드코딩은 커스텀(SDK) 말고는 필요 없다." 이어진 결정:
- **코드로 정의된 에이전트(SDK 수기·스킬 코드젠)는 한 부류** — UI는 구성을 소유하지 않는다
  (편집 불필요), **플레이그라운드에서 테스트만 가능하면 된다**. 원격 code 에이전트의 기존 원칙
  ("읽기 전용, 구성은 코드가 소유")을 인프로세스 코드 에이전트에도 일관 적용.
- **artifact 데모 2종(slotfill·targeting)은 제거** — 인스턴스 0·폼 미노출, 역할은 노코드판
  (artifact_form)이 흡수. 유일 소비자였던 **targeting-catalog MCP도 같이 제거**.
- **plan-execute-demo(시드)는 노드형(pipeline) 에이전트로 대체** — dev DB는 이미 전환돼 있음
  (convert-plan-demo-pipeline.mjs), 시드를 현실에 맞춘다.

## 실행

1. **artifact 데모 제거**: `runtime._bootstrap_builtins`의 등록 2줄+import, `flows/artifact.py`의
   `SlotFillDemoAgent`·`TargetingDemoAgent` 클래스. `ConfigDrivenArtifactAgent`(artifact_form)와
   공통 뼈대(ArtifactAgentBase)는 유지.
2. **targeting-catalog MCP 제거**: 서빙 도구 정의(list_entities/get_entity)·reconcile 시드 항목·
   dev DB 행. 사전 측정: 이 MCP를 배선한 에이전트 0 확인 후 삭제.
3. **시드 plan-execute-demo → 노드형**: dev DB의 전환된 config.nodes를 시드로 미러(impl=pipeline).
   `plan_execute` impl 자체는 유지 — SDK CustomAgent의 레퍼런스(스펙 085)이자 suite 픽스처.
4. **코드 정의 impl UI 봉인**: 범용 5종(``·orchestrate·orchestrate_ranked·artifact_form·pipeline)
   밖 impl 에이전트는 상세에서 편집 숨김 + "코드 정의 — 구성은 코드가 소유" 안내(원격 code와 동일
   표현). AgentForm의 "밀어 넣기" 폴백(미지 impl 옵션 추가) 제거. **플레이그라운드·API는 무변경**
   (suite 픽스처는 API로 생성 — UI 정책이지 런타임 제한 아님).
5. **agent-flow 스킬 규약 반영**: 코드젠 에이전트는 UI 편집 대상이 아니다 — 수정은 코드에서.

## 범위 밖 (OUT)

- `route`·`plan_execute`·`orchestrate_ranked` impl 제거 — 유지(각: 코드젠 템플릿+suite 3 /
  SDK 레퍼런스+suite / 조율 전략+suite).
- 백엔드에서 코드 정의 impl의 API 생성/수정 차단 — UI 정책만(suite·개발 경로 보존).

## 검증

- 제거 후 grep 0(artifact_slotfill·artifact_targeting·SlotFillDemo·TargetingDemo·targeting-catalog).
- 시드 무결: throwaway DB(alembic+seed)에서 plan-execute-demo impl=pipeline·targeting-catalog 부재.
- UI: suite-route(코드 정의) 상세=편집 없음+안내, personal-secretary(범용)=편집 그대로(스크린샷).
- 회귀: suite 관련 시나리오(plan-execute·route·pipeline)·verify_156(서빙)·metrics 패널·tsc/build.

## 완료 조건

- 데모 잉여 소멸(grep 0) + 신규 시드가 노드형 데모를 심음.
- 코드 정의 impl 에이전트 UI 읽기 전용(플그 테스트 가능 유지).
- 회귀 그린.
