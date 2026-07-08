# 스펙 235 — 비영속(ephemeral) 1회성 추론 에이전트 (DB 적재 전면 스킵)

## 배경 (사용자 요구 2026-07-08)

"아주 간단한 1회성 추론 기능을 제공해야 한다. 그러려면 **기능을 다 끄고** 제공할 수 있어야 한다." →
명확화: **"기능 다 끄기 = DB에 적재하지 않는 것"**(트래픽이 많을 수 있고, 기록이 무의미할 수 있어서).

기존 `persistHistory=false`는 **메시지만** 스킵하고 세션 행·카운터·commit은 남긴다(반쪽). 진짜 비영속엔
그 위 플래그가 필요.

## 변경

### 백엔드 (packages/api/src/api/chat.py + schemas.py + serializers.py)
- `config.ephemeral`(bool, 기본 false) 신설. `_persist`가 `ctx["ephemeral"]`이면 **즉시 return None**(세션
  해결·행 생성·카운터·commit 전부 무접촉). 신규 chat·승인 재개 두 경로 공용.
- 메모리 read/write도 ephemeral이면 off(`used_memory`에 `not ephemeral` — 신규·재개 대칭). 완전 stateless.
- **체크포인터 미부착**(codex 적대 검증 봉합): `ckpt = None if ephemeral`. AsyncPostgresSaver를 안 붙여
  `checkpoints/checkpoint_writes/blobs` 미기록. ~~HIL interrupt 구조적 불가 → `_create_approval` 미도달~~
  **← 정정(스펙 237 실측 반증)**: 체크포인터가 None이어도 interrupt는 발생해 `_create_approval`이
  세션+Approval 행을 썼다(계약 위반 실경로). 스펙 237이 interrupted 분기에 명시 게이트를 넣어 봉합
  (verify_237 T5가 회귀 가드).
- **Langfuse 트레이스 스킵**(신규·재개 경로 대칭): 외부 관측 기록도 계약상 무의미하므로 off.
- **다배선 미러링**(persistHistory 선례 — 빠뜨리면 model_dump가 조용히 드롭): schemas.py AgentConfig +
  AgentOut, serializers.py(cfg→top-level), admin api/types/mockData, AgentsView 매핑 3곳, AgentForm.

### 관리 UI (AgentForm.tsx) — **경계 구분**(사용자 지시)
- 세부 설정 Collapse를 폼 표준 `SectionHeader`로 **모델 동작 / 저장·영속** 두 경계로 나눔(antd v6 Divider
  orientation 타입 이슈도 회피 — 폼의 기존 섹션과 동일 컴포넌트).
- 저장·영속 영역 최상위에 **비영속(1회성)** 토글. 켜면 하위(채팅 히스토리·대화 저장)를 **비활성**(무의미)
  처리 + 안내 문구.

## 검증
- **verify_235**: 실 AsyncPostgresSaver 초기화 후, ephemeral 채팅 1턴 전후 **session/message + checkpoints/
  checkpoint_writes/checkpoint_blobs/approvals 전부 Δ=0**. 대조군(비-ephemeral)은 session Δ1·message Δ2·
  **checkpoints Δ3** → E6이 vacuous 아님을 **인과 증명**(봉합 없으면 ephemeral도 3행 썼을 것). VERIFY235_OK.
- verify_233 무회귀(PASS=27·IGNORE-OK=29 — 스키마 필드 추가가 매트릭스 안 깸).
- tsc 0, 브라우저(폼 경계·토글·비활성 연동).
- codex 적대 2라운드: R1이 _persist 밖 3갭(approval·체크포인터·langfuse) 적발 → 봉합, R2가 인과 봉합 확인.

## 완료 조건
- ephemeral=true 에이전트는 DB 쓰기 0(세션·메시지·메모리). persistHistory와 구분(상위집합). 폼에서 경계
  구분되어 설정 가능. 검증 사다리 3런.

## 비고 / 경계
- **HIL·artifact ask/form 등 체크포인트 재개형 흐름은 ephemeral에서 미동작**(의도된 기능 축소) — 체크포인터가
  없어 interrupt/승인/재개가 성립 안 함. ephemeral은 **도구 없는 순수 1회성 추론** 전제.
- **도구 자체의 외부 부작용은 chat.py로 못 막는다**(codex R2): ephemeral도 MCP/RAG/broker를 빌드하므로,
  외부에 쓰는 도구를 붙이면 그 쓰기는 별개. "앱 DB 적재 0"은 보장하나 "순수 추론"을 강제하려면 도구 자체를
  금지/read-only 제한해야 — **후속 결정 사항**(현재는 문서화된 경계, 실사용은 무도구 전제).
- persistHistory=false(메시지만 스킵·세션 유지)는 **윈도우 모드**로 유지(별개 용도).
