# 373 — 정책 게이트를 read 형태 SQL 시드로만 검증하면 순환이다

## 맥락

스펙 372 평가 게이트는 다른 서브시스템(평가 파이프라인)이 **쓴** `EvalRun` 행을 **읽어** 배포를
판정한다. 게이트 검증 verify_372는 그 행을 **직접 SQL로 심었다** — 게이트가 읽는 형태를 테스트가
스스로 만든 것이라, "평가가 실제로 쓰는 형태가 같은가"는 검증 밖(순환). 형제 verify_240은 실제
평가를 돌리지만 **활성 버전만** 평가해(먼저 activate 후) 게이트의 실 시나리오(미오픈 스크래치
지정 평가)를 안 탄다. 두 테스트가 각자 초록인데 그 사이 이음매는 한 번도 실행 안 됨.

## 교훈

- **정책 게이트가 "A가 쓴 것을 B가 읽어 판정"하면, B 검증을 A가 쓰는 형태로 시드하는 건 순환이다.**
  seam이 어긋나도(version 문자열 포맷·점수 스케일 0..1 vs 0..100·귀속 대상이 active vs 지정) B의
  시드 테스트는 자기 형태를 심으니 초록으로 남고, 실 UI 흐름은 조용히 전멸한다(예: 스크래치를
  아무리 평가해도 게이트가 영원히 0을 읽어 못 엶). 이는 fake-mirrors-real(127)·mock-degenerate(143)·
  two-mechanisms(359)·explicit-serializer-drops(369)와 같은 축.
- **닫는 법**: **실 생산자(A)가 쓴 행을 소비자(B)가 읽는 e2e 하나.** 시드 금지, 실 파이프라인 실행.
  결정적 통과 점수가 어려우면(mock은 semantic 통과 비결정적, 366) 임계를 우회 설정(min_score=0)해
  **문자열/귀속 이음매**를 먼저 닫고, **스케일은 실 값 범위 단언**(score∈[0,1])으로 핀한다.
- **비용 대비**: 코드 변경 0(이음매는 코드상 이미 정합이었음)·테스트 1개·기존 픽스처 재사용. 값은
  미래 드리프트(누가 score를 0..100로 저장, version을 int로 저장) 시 게이트 전멸을 그물이 잡는 것.
- **분류 자동**: run_suite는 `httpx`/`BASE=http` 문자열로 http 카테고리 자동 판정 — 실서버 통합
  테스트는 별도 등록 없이 `make test-all`/`run_suite http` tier에 앉는다(기본 그물 밖이나 고아 아님).

[policy-gate-read-seed-is-circular, real-producer-e2e, string-and-attribution-seam,
scale-pin-by-value-range, threshold-bypass-to-isolate-seam, two-subsystem-contract-drift]
