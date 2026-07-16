# 383 — test-all 상태 오염은 실회귀를 가린다: 결정적 스캔이 신뢰 신호

## 맥락

캠페인 374 리팩터(381 rag 분할·382 ctx→DTO) 후 test-all(http 층) hygiene 중, **실행마다 실패
목록이 요동쳤다** — 1회차 rag(312·331~335)+eval, 2회차 114·120·143·161·233·235…, 3회차 055·068·
072·101…. 공유 dev DB에 순차로 던지는 http 테스트가 서로를 오염시켜(커넥션 풀·시드 잔여·이벤트루프)
비결정적이다(run_suite도 그래서 http를 씨앗 그물서 뺀다).

## 교훈

- **상태 오염은 실회귀를 가린다 — 한 번의 test-all은 권위가 아니다.** 진짜 DTO 회귀(verify_068의
  `apr_ctx` dict→`_create_approval`가 `ctx.session_pk`에서 AttributeError)가 **1·2회차엔 안 보이다
  3회차에 나타났다**. 앞 실행에서 다른 테스트가 먼저 죽어 그 지점에 도달을 못 했을 뿐. "test-all이
  초록/이 실패는 무시" 판단을 한 번의 실행으로 내리면 회귀를 놓친다.
- **회귀를 찾는 신뢰 신호는 결정적 스캔이다(테스트 실행이 아니라).** 계약/임포트 표면 회귀는 코드
  구조 사실이라 DB·순서와 무관하게 grep으로 전수된다:
  - ctx-dict 회귀(382): **ctx 소비함수 호출** grep(`_create_approval\(|_persist\(|_a2a_stream\(|
    _rag_tools_for\(|resolve_agent_runtime\(|_load_context\(`)로 dict 넘기는 테스트를 전부 찾음 →
    049·068·081·085·089·268이 닫힌 집합(068이 마지막). 시그니처 키(`"session_pk"` 등) dict 리터럴은
    소비함수에 안 넘기면 무해(trace·config 용도)라 함께 교차.
  - 심볼 rename 회귀(375): `_TOOL_*_CAP` grep으로 verify_151 하나 확정.
  - 패키지 표면(381): `from api.rag import` grep으로 재수출 누락 전수.
  이 스캔들이 "test-all 요행"보다 강하다 — 오염 뒤에 숨은 것도 잡는다.
- **회귀 vs 사전존재는 baseline 대조로 가른다.** 의심 실패는 `git stash` + `git checkout <리팩터
  이전 커밋> -- packages tests/<파일>` 후 실행 → 동일 실패면 사전존재(068 D6 resume 500 = "connection
  is closed" 인프라, baseline 동일). 주의: baseline checkout이 삭제된 파일(rag.py)을 되살려 staged로
  오염 → 복원 시 `git rm -f` + `git checkout HEAD -- packages` + `git stash pop` 순서로 정리.
- **격리는 정직화지 은폐가 아니다 — 실 갭은 고치고, 드리프트만 격리.** hygiene에서 verify_347의
  block_versions 미분류는 **실 거버넌스 갭**(스펙 369 테이블이 자원 정책 대장 밖)이라 격리 대신 **코드
  수정**(reclaimed+chokepoint 분류). 반면 promptStale(기능 진화)·eval 스키마 드리프트는 사유 달아
  격리. "제품결함 후보"(233 orchestrate_ranked 위임)는 그 표현 그대로 사유에 남겨 다음 조사로 넘김.

[test-all-pollution-nondeterministic, deterministic-scan-beats-flaky-run, consumer-call-grep-closes-set,
baseline-diff-separates-regression, quarantine-is-honesty-fix-real-gaps]
