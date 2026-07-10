# 273 — 오버라이드 드로어 기억 컨트롤을 공용(MemoryFields)으로 통일

> 271 공용화의 잔여 표면. 사용자 검증 요청("정말 공용 컨트롤로 통합되었는지")에서 측정으로 발견:
> 플레이그라운드 오버라이드 드로어가 `DEPTH_OPTS` **사본**(내용 동일)과 자체 "단기 기억" Select를
> 보유 — drift 위험(옵션을 한쪽만 고치면 어긋남). 사용자 지시: 최소수선(export/import) 말고 **전체
> 교체** — 개인용 서비스라 작업 단위를 작게 쪼갤 필요 없음.

## 현재 구조 (측정)

- `OverridePanel.tsx:55-62` — `DEPTH_OPTS` 로컬 사본(MemoryFields 14-21과 동일).
- `OverridePanel.tsx:471-478` — `<Field label="단기 기억"><Select options={DEPTH_OPTS}/></Field>` 자체 렌더.
- 장기 기억은 좌측 "이 대화에서 쓸 것" PickerGroups의 '기억' 그룹(226-236행)에 도구와 함께 —
  **271 이전의 AgentForm 구조와 동형**(271이 AgentForm에선 기억을 PickerGroups에서 빼 공용 컨트롤로 이동).
- 비영속 미선택-잠금 로직(232행)이 LongTermMemoryField의 `ephemeral` prop과 **중복 구현**.

## 변경 (OverridePanel 직접형, step 1)

AgentForm 271 구조를 미러:

1. 로컬 `DEPTH_OPTS` 삭제, `ShortTermMemoryField`/`LongTermMemoryField` import.
2. 좌측 PickerGroups에서 **'기억' 그룹 제거**(도구만 남김) — OV_FIELD/ovSelected/ovToggle을 mcps 단일로 축소.
3. 우측 세부에 **기억 구획**: `ShortTermMemoryField`(value=draft.historyDepth, hint=AgentForm과 동일) +
   `LongTermMemoryField`(value=draft.memories, options=blocks.memory−단기(세션), ephemeral=isEphemeral —
   미선택-잠금·placeholder·도움말이 공용에 이미 있으므로 중복 로직 소멸).
4. 드래프트 상태·diff 계산(`sameSet(memories)`)·적용 payload **무변경** — UI 표현만.

## 완료 조건 (측정 가능)

1. `DEPTH_OPTS` 정의가 저장소에 **1곳**(MemoryFields.tsx) — `grep -rn "DEPTH_OPTS" admin/src` 파일 1개.
2. `ShortTermMemoryField|LongTermMemoryField` 소비처 = AgentForm·NodeListEditor·**OverridePanel** 3곳.
3. 오버라이드 드로어 기능 불변: 단기 변경→적용→diff 칩 표시, 장기 선택→적용 payload에 memories 반영(e2e).
4. 좌측 피커에 '기억' 그룹 없음(도구만), 비영속 에이전트에서 장기 새 선택 잠금 유지.
5. tsc 0, 기존 오버라이드 e2e(109/122/123 계열 스크립트) 구조 단언 노후 시 같은 턴 갱신(회고 246 ④).

## 무회귀·경계

- 서버 allowed 키·오버라이드 payload 스키마 무변경.
- 조율형(capabilities) 분기 무변경 — 직접형만.
- 코드/외부 에이전트 read-only 분기 무변경.

## 검증 (사다리)
- e2e(기능적): 드로어에서 공용 컨트롤 값 변경→적용→적용 상태(diff/payload) 단언.
- 자체 사본 소멸은 grep 카운트로 측정(자가선언 금지).
- 적대(codex): UI 전용 소규모라 생략 검토 — 상태·payload 무변경이므로 경계 없음(스킵 사유 명시).

### 검증 결과
- **grep 측정**: `DEPTH_OPTS` 정의 = MemoryFields.tsx **1곳**(사본 소멸), 공용 컨트롤 소비처 =
  AgentForm·NodeListEditor·OverridePanel **3곳**. tsc 0.
- **verify-273-override-shared-memory.mjs 9/9 GREEN** — 구조(피커에 '기억' 그룹 없음·공용 라벨/도움말)
  + **기능 왕복**: 공용 컨트롤로 단기=0·장기 '장기 기억 (mem0)' 선택→적용→실제 chat 요청 캡처
  `overrides={"memories":["장기 기억 (mem0)"],"historyDepth":0}` — 드래프트→payload 배선 실증.
- **형제 스크립트 노후 갱신(회고 246 ④)**: shot-override-109(시드 에이전트명 의존+249 이전 접이식
  단언 → 자가 생성 에이전트+Steps 구조로 재작성, 6/6)·shot-override-no-crosstoggle-123(249 스텝
  도입 반영 — "다음" 이동 추가·'세부 설정' 접이식 소멸, 3/3 ALL PASS). 둘 다 273 전부터 낡아 있었음.
- **오버레이 감사 FAIL 0** — pg-override 모바일/데탑 오버플로 offender 0. (nav 미스 3종
  pg-inspector·users-grant-tab·agent-create/mobile은 273 무관 하네스 선행 이슈 — 백로그 후보.)
- **육안**: 좌=도구 피커·우=Temperature+단기+장기, AgentForm과 동일 모습. 스텝 제목
  "도구 · 지식 · 세부"→kind별("도구 · 기억 · 세부"/"맡길 것 · 세부")로 실내용 정합.
- **codex 스킵(합의 필요 사유)**: UI 전용·상태/서버 payload 스키마 무변경·기능 배선은 요청 캡처로
  실증 — 파괴/인가/비가역 경계 없음. 사용자가 원하면 후속 적대 리뷰 가능.
