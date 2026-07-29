# 스펙 431 — suite 진행 노출(스트리밍 줄 + 진행 파일)

## 문제(구남님 제안, 2026-07-19 백로그)

장시간 스위트가 밖에서 안 보인다. 근인 실측:
- **씨앗 그물(run_suite.py)**: 결과를 그룹 완료 후 **일괄 출력** — db 그룹(46개 직렬, 수 분)이 도는
  동안 로그가 침묵(tail -f 무용). 스트리밍 부재가 뿌리.
- **실모델 배터리(suite/run.py)**: 시나리오별 줄은 스트리밍되나 **n/total 카운터·기계가 읽을 진행
  파일 없음** — "몇 분 남았나"를 알 수 없다.

## 결정

[[long-turns-need-eta-and-progress]]의 도구화 — 사람(tail -f)과 기계(파일 폴링) 양쪽 채널.

1. **`tests/_progress.py`(신설, 공용)**: `ProgressWriter(runner, total)` — `start(name)`/`done(name, ok)`
   호출마다 `/tmp/suite-progress.json`을 원자적(tmp+rename) 갱신:
   `{runner, total, done, ok, fail, current, elapsedS, updatedAt}`. **실패 무해**(진행 기록이 그물을
   못 깨게 — try 흡수). 두 러너가 공유(사본 금지).
2. **run_suite.py**: 그룹 실행을 스트리밍화 —
   - db 직렬 루프·unit/asgi/http 병렬(`as_completed`)에서 **끝나는 즉시** `[n/N] name ok|FAIL (x.xs)`
     한 줄 출력 + ProgressWriter 갱신. 기존 그룹-후 판정 출력(격리·그물 분류)은 유지(요약 축).
3. **suite/run.py**: `_print_row`에 `[n/N]` 접두 + ProgressWriter 갱신(시나리오 시작·완료).

## 완료 조건(측정) — 결과

1. ✅ 그물 실행 중 tail 실측: db 그룹 직렬 구간에서 `[48/93] verify_038_batch_cleanup.py ok (1.3s)`
   실시간 스트리밍(종전 침묵 구간 소멸).
2. ✅ 진행 파일 중간 측정 2회: done 48→60(current·elapsedS 갱신) — 기계 채널 작동.
3. ✅ 종료 시 done==total(93/93)·ok 92/fail 1이 요약(통과 92·실패 1)과 정확 일치.
4. ✅ 그물 무회귀(유일 실패=이 스펙 자신의 INDEX 줄 타이밍 — 431 INDEX 추가로 해소, 코드 회귀 0).
5. **배터리(suite/run.py)는 컴파일 검증까지** — 라이브 스모크는 구남님 중단 지시로 생략(수정=기계적
   `[n/N]` 접두+진행 호출 2줄). 다음 배터리 실행이 자연 실증(정직한 경계).

## OUT(경계)

- ETA 추정(남은 시간 계산 — done/total과 elapsed로 소비자가 셈).
- suite 진행의 admin UI 표면(파일·로그 채널까지 — UI는 필요 시 후속).
- 씨앗 그물 그룹-후 판정 출력 개편(스트리밍 줄과 요약 이중은 의도 — 실시간성과 분류 정확성 분리).
