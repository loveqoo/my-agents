# 029 — 유저 메모리 통합·재적재 회고 (스펙 039, P3-b)

> 지배 스펙: `docs/spec/archive/039-user-memory-consolidation.md`. 관련 learning: [[038-adversarial-review-finds-what-invariants-miss]],
> [[037-floor-the-destructive-knob]], 034-invariant-and-delta-tests, 035-guard-the-source-not-the-copy, 030-verify-ui-in-a-real-browser.

## 무엇을 했나

- 두 번째 배치 작업 **`consolidate_user_memories`**: 임계치 초과 유저의 user_id 축 장기기억을 LLM으로
  더 적은 사실로 통합 → 원본을 `MemorySnapshot`에 **commit한 뒤** 통합본 적재 → 박제한 mem_id만 삭제.
- 038 토대(runner/BatchRun/BatchConfig/JOBS/service/BatchView) 재사용 — 새 패널·새 작업만 증분.
- **격리 유지를 위한 Scaffolding**: chat.py(langgraph 의존)에서 mem_cfg 해석기를 `mem_config.py`로 추출.
  배치 프로세스가 `default_mem_cfg`를 쓰되 langgraph/agent.main을 끌어오지 않게(sys.modules로 실측 확인).

## 합의가 스코프를 좁혔다 (쉬운 말로 다시 설명한 값어치)

- AskUserQuestion 3분기로 #6의 의미("누적 통합·압축")·안전("스냅샷 후 교체")·트리거("cron+임계치")를 먼저 못박음.
- 사용자가 "비면" 같은 용어가 낯설다 → **쉬운 말로 재설명**하니 두 후속 결정이 명료해졌다:
  (1) dry-run도 LLM을 부른다(정직한 미리보기), (2) 자동 롤백은 빚(스냅샷=앵커, 수동 복원 문서화).
  - 교훈: 사용자의 언어로 내려야 결정이 빨라진다. 전문용어는 합의의 마찰이다.

## 적대적 검증이 *내가 설계한 안전망의 빈칸*을 찾았다 (이번의 핵심)

내가 스펙에 **안전 불변식 5개**를 직접 적고, 그 5개를 검증하는 verify_039도 직접 썼다. 전부 통과했다.
그런데 서브에이전트 적대 리뷰가 **CRITICAL 2건**을 찾았다 — 둘 다 내 불변식이 *구조적으로* 못 막던 범주:

1. **미축소 쓰레기 교체** — 불변식 2는 통합 결과가 *빌 때*만 삭제를 막았다. 모델이 거부문·머리말·원문
   에코를 뱉어 **비지 않은** 리스트가 나오면 진짜 기억 N개가 쓰레기로 교체·삭제된다. 내 테스트는
   "빈 결과" 케이스만 단언했으니 통과할 수밖에 — **내가 상상한 실패만 검증한 것**.
2. **프롬프트 잘림 손실** — 임계치 초과 = 기억 많은 유저인데, 그 전부를 한 프롬프트에 넣는다. 컨텍스트
   초과 시 입력이 잘리면 잘린 사실은 통합에서 누락되는데 **삭제 루프는 원본 전체를 지운다** → 영구 손실.

→ **실행 지점에 floor**(learning 037 재적용): `_valid_consolidation`(비거나 미축소면 스킵) +
   `_MAX_CONSOLIDATE_INPUT=200`(초과 유저 스킵) + 삭제<스냅샷 경고 로그. dry-run은 `skip` 키로 정직히 표기.
   verify_039에 `[4b]`(미축소 N→N → 스킵) 추가. 잔여(줄어든 거부문 등 의미적 쓰레기)는 스냅샷+dry-run
   백스톱으로 §7 빚에 명문화. **자세히 → [[038-adversarial-review-finds-what-invariants-miss]]**.

다른 지적은 흡수 또는 빚으로 분류: `add(infer=False)` 순수 insert 가정은 verify `[2]`(deleted==N+최종==STUB)로
**실측 핀**(근거 없는 가정 → 측정으로 전환), mem_cfg detached-session 우려는 순수 dict 반환이라 무해,
SET NULL 링크 단절은 created_at으로 수동 복원 가능 → 빚.

## 검증 메모

- verify_039: **34 단언 ALL PASS**, 실 mem0(공유 pgvector). `_consolidate`만 결정적 stub, 나머지 파이프라인
  (add/snapshot/delete)은 실제. **실 유저 보호**: `list_memories`를 게이트 패치해 검증 유저만 후보가 되게 —
  작업이 전 User를 스캔해도 실 유저 기억은 불변(035 "복사본 말고 원본을 지켜라"의 변주: 테스트가 공유
  자원을 오염시키지 않게 경계에서 막음).
- 브라우저: shot-memory-039 3컷 — 패널 뷰·임계치 저장·dry-run 토스트. **dry-run이 실 유저 3명을 스캔하고
  0 변경**(후보 0명)을 라이브로 확인 → 불변식 4(dry-run 무변형)를 실 데이터에서 눈으로 검증.
- stale 회귀 수선: jobs.py가 이제 memory를 임포트하므로 verify_038 `[6]`(모듈 단위 "memory 미임포트")을
  `cleanup_sessions` 함수 단위 + 호출(`memory.`) 단위로 좁힘. runner 변경(`run_id` 전달)에 `_boom` 시그니처도 맞춤.

## 다음

- P3 다음 항목(로드맵 #?) — Scaffolding에서 페이즈 확인.
- 빚(§7): 의미적 쓰레기 출력 검증(센티넬/패턴), 청크 통합, 자동 롤백, 동시 실행 잠금(038 계승), 후보 스캔 최적화.
