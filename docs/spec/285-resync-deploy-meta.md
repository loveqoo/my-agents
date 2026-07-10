# 285 — resync 시 배포 메타(commit·repo·runtime) 재보고

> 사용자 결정. 배경: Internal(Code)의 버전 = SDK/카드가 **등록 시점에 신고한 commit**(자기 신고
> 스냅샷) — 재배포 후 재등록하지 않으면 낡는다. resync(081)는 endpoint·상태·카드 스냅샷만 실측
> 갱신하는 비대칭. 상태는 실측인데 버전은 신고라는 어긋남을 resync가 메꾼다.

## 변경 (resync_agent, 스펙 081 확장)
- 카드 재fetch 후 **code 에이전트(x-my-agents 확장 보유)**면 `deploy` 메타 재반영:
  - `repo`(200 clip)·`runtime`(200 clip) 갱신(값 있을 때만 — 카드에서 사라졌으면 기존 보존,
    merge-preserve: 재동기화가 필드를 소리 없이 파괴하지 않게).
  - `commit`(80 clip, 057 F3 길이 하드닝 동일)이 **바뀌었으면**: 기존 active 버전 행 archived →
    같은 이름 행이 이미 있으면 그 행 승격, 없으면 새 AgentVersion(commit, active) 추가 →
    `active_version=commit`. **057 F4 불변식 유지**: active_version은 항상 실재 active 행.
  - 동일 commit이면 무변경(중복 버전 행 생성 금지).
- external(확장 없음)·확장이 사라진 카드 → 기존 동작(카드 스냅샷 갱신이 card.version 최신화 담당,
  deploy 메타는 보존).
- manifest(config: model/persona/mcps) 재반영은 **범위 밖**(후속 판단 — 표시용 config 통째 갱신은
  sync-wholesale-replace 계열 위험 검토 필요).

## 완료 조건 (측정 가능)
1. 라이브(081 하네스 패턴): connect(commit A) → 카드 commit B로 변경 → resync →
   `agent.commit==B`·`active_version==B`·구 행 archived·새 행 active (실 DB 왕복).
2. 동일 commit resync → 버전 행 수 불변(중복 생성 없음).
3. 확장 없는 카드(external) resync → deploy 메타 불변(무회귀).
4. A→B→A 재왕복: 기존 A 행 승격(중복 A 행 금지).

### 검증 결과
- **verify_285_resync_commit.py 11/11 ALL PASS**(실 인프라 rung 2 — 081 하네스 패턴, 실 DB+스레드
  카드 서버): ①connect commit A ②동일 commit resync 무변경(행 수 불변) ③재배포 B→resync→commit/
  active_version/버전 전이(구 행 archived·새 행 active)+repo·runtime 재보고 ④A→B→A 재왕복=기존 행
  승격·중복 0 ⑤확장 소실 카드→메타 보존(**판별자=카드 스냅샷 갱신 여부** — 도달실패 경로와 구분).
- **테스트 함정 2건**: ⓐ몽키패치 함수가 모듈 전역을 통해 자기 자신을 호출(재귀)해 ⑤가 "도달 실패"
  경로로 잘못 통과 — 원본을 먼저 캡처. 판별자 없는 보존 단언은 두 경로를 구분 못 함.
  ⓑverify_081_live가 112(관리 게이트) 이후 principal 없이 직호출이라 낡아 있었음 — superuser
  SimpleNamespace로 수리(같은 턴, 245 "안 만든/안 돌린 경로" 계열).
- 081 라이브 8/8 무회귀. codex 스킵(카드 자기신고 모델은 057 기존 리스크 그대로 — 이 변경은 신고
  갱신 시점만 추가, 게이트·SSRF 경계 무변경: resync는 저장된 cardUrl만 fetch).
