# 366 — 게이트 밖 테스트는 썩고, 되살리면 진짜 버그를 뱉는다

**맥락**: e2e Playwright 스위트(`tests/e2e`)가 `make test` 밖이라 아무도 안 돌려 조용히 드리프트로
썩음. 스펙 365 전수조사에서 돌리자 api 11 실패 + admin/mobile 인증막힘. **전부 개명 무관 기존 부채**
(시드 개편·기능 제거·계약 변경·이름 규칙 강화가 누적). 재정합해 39/39 green + 실행 가능화(`make e2e`).

## 세 갈래 교훈

1. **게이트 밖 테스트는 커버리지가 아니라 부채다** — 실행 안 되는 테스트는 "있다"는 착시만 준다.
   드리프트 유형: 시드 이름(qwen3.6-35b→mock-llm), 제거된 기능(/permissions·/vector-tables 404),
   응답 형태(/sessions 배열→{items,total}), 이름 규칙(한글·마침표 금지), mock 출력 시그니처. 봉합은
   **시드/계약 상수를 한 파일(seed.ts)로 수렴**해 다음 변경 때 한 줄만 고치게. 근본 방지는 **게이트에
   묶기**(make e2e) — 안 묶으면 또 썩는다. [[compounding-vs-latent-axis]](드리프트는 잠복 축).

2. **결정적 mock는 semantic을 못 한다 — 테스트를 mock 능력에 맞춰라** — mem0 "저장→다른 문구 회상"은
   실 임베딩이 필요한데 mock은 sha256 exact-match만. 채팅 경로 mem0 추출은 회상가능 메모리도 안 남김
   (verbatim조차 0). 회상 hits 단언은 mock서 불가 → 그 단언을 빼고 결정적 부분(스트리밍·트레이스·세션
   영속)만 남김. 회상 기능은 직접 시드하는 스펙 363·매트릭스 verify_233 소관(맞는 도구에 맡김).

3. **되살린 테스트는 숨어 있던 진짜 버그를 뱉는다** — 실행가능해진 mobile 가드가 `프로바이더·모델`
   뷰 iPhone SE(320px) 콘텐츠 16px 가로 오버플로를 잡음(개명·테스트 무관 제품 버그). 원인=마스터/디테일
   Panel `minWidth: 280/320`이 좁은 컨테이너로 못 줄어듦. 봉합=`minWidth: 'min(Npx, 100%)'`(데스크톱
   나란히 유지·모바일 축소). **테스트 green을 위한 test 손질만 하지 말고, 테스트가 가리키는 실 결함은
   고쳐라** — 되살리기의 배당금이다.

## 브라우저 E2E 인증 프로비저닝(재사용 패턴)

머신 Bearer 토큰은 데이터 라우트는 통과(GET /agents 200)하지만 `/users/me`를 fastapi-users 유저로
못 풀어 401 → SPA `getMe()` null → 로그인 화면 막힘. 표준 해법(백엔드 무변경): **Playwright global-setup이
UI 오리진(same-origin /api 프록시) 경유로 쿠키 로그인 → `storageState` 저장 → 브라우저 프로젝트가
이어받아 자동 인증**. 쿠키가 Bearer보다 우선(cookie+Bearer=200)이라 VITE_API_TOKEN 병존도 무해.
관련: [[verify-ui-in-browser-proactively]].
