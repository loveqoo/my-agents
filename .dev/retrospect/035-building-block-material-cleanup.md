# 035 — 빌딩블록 재료 정리 회고 (스펙 046 · 마스터 044 배치 2)

> UI 테스트 #4(웹 에이전트에 파일/터미널/repo/k8s 권한 불필요)·#5(미구현 MCP 정리).
> 테마: **순수 웹 에이전트 플랫폼에 맞게 카탈로그를 비운다.** 권한 5·MCP 4·데모 에이전트 2 제거.

## 무엇을 했나

- seed.py 코드층(PERMISSIONS 3·MCP_SERVERS 6·AGENTS 2·APPROVALS 빈 리스트)을 줄이고,
  라이브 DB는 `cleanup_046_blocks.py`(기본 dry-run, `--apply`로 트랜잭션)로 정리.
- 유지 에이전트(Research)의 dangling soft-ref(config + 모든 version.config의 files.read·filesystem)를
  flag_modified로 strip.
- 비범위 명시: runtime `_APPROVAL_ACTIONS`(github.merge_pr→repo.merge 등)는 카탈로그가 아니라
  런타임 정책 → 미변경. 게이트는 "살아있되 트리거만 소멸"로 설계.
- 검증 사다리 3rung + 브라우저(22/22 단언) 통과.

## 잘된 것

1. **dry-run이 라이브 DB 스케일을 드러냄.** 시드는 세션 5·승인 2였지만 라이브엔 세션 16·승인 8
   (과거 테스트 잔존). 적용 전 리포트로 그 차이를 봤기에 cascade가 무엇을 지우는지(16 세션 +
   messages) 알고 진행. learning 025(시드만 고치면 안 됨—라이브 DB도)가 정확히 적중.
2. **soft-ref strip을 별도로 처리.** FK가 없는 JSON 참조(config.permissions/mcps[])는 권한 행을
   지워도 자동 정리 안 됨. learning 042(참조 양방향)대로 들어오는 참조(권한 행을 쓰는 에이전트
   config)를 명시적으로 strip. 검증 I4(dangling 0)가 config + version.config 둘 다 확인.
3. **카탈로그/정책 경계를 지킴.** "github/kubernetes MCP를 카탈로그에서 빼되 runtime 게이트는
   보존" — 메커니즘은 살리고 트리거만 죽이는 게 사용자 의도("HIL 041 보존")와 정확히 일치.
   verify_041 green 유지로 증명.

## 아팠던 것 (적대 리뷰가 잡음)

- **B1 stale 픽스처.** shot-agents-037.mjs가 삭제 대상 Code Reviewer를 클릭하고 있었음 —
  제거 후 즉시 깨질 테스트. Research Assistant로 재지정. 카탈로그를 비울 때 *그 재료를 쓰는
  테스트 자산*도 같이 깨진다 — learning 042의 또 다른 면.
- **B2 통합 rung 상실(→ learning 045).** probe_041이 github MCP + Code Reviewer를 태워 chat.py
  글루를 증명했는데, 046이 그 빌딩블록을 *설계상* 제거하니 시나리오가 더는 시드 안 됨. 게다가
  agent_pk 조회가 `scalar_one()`이라 에이전트 부재 시 크래시. graceful SKIP으로 고치고 §7에
  rung 상실을 빚으로 기록.
- **W1 리포트가 pending 미경고.** cleanup 리포트가 제거 권한 참조 승인을 나열하되 pending 여부를
  강조 안 함 — 045 배지에 샐 수 있는 위험. ⚠ 경고 추가(현재 pending 0이라 무해하나 미래 방어).

## 배운 것 → 자산

- learning **045**: 통합 픽스처가 데모 시드 데이터에 결합하면, 카탈로그를 비울 때 통합 rung이
  함께 증발한다 — 셀프픽스처로 격리하라. (040의 반대편: rung을 *얻는* 법이 040이면, *잃지 않는*
  법이 045.)
- 재사용: learning 025(라이브 DB drift)·042(양방향 참조)·037(파괴적 경계)·043(코드층/데이터층
  분리)·memory adversarial-review-before-destructive-ship — 모두 이번에 그대로 적용됨. 새 실수가
  아니라 *기존 교훈의 정확한 재적용*이 대부분이었다는 게 복리의 신호.

## 남은 빚 (§7, 050 후보)

- 라이브 DB 비-시드 잔존(테스트 세션·승인·Probe A2A 정크 에이전트)은 050에서 전수 정리.
- 삭제 16 세션의 langgraph 체크포인트 고아 행(FK 없음, 기능 무해) — 050 스토리지 정리 후보.
- 8 고아 승인(repo.merge/k8s.write, resolved, pending 0) — 045 배지 불변, 050에서 정리.
