# 350 — 스펙 427 회고: 사고 예산 굶김 + 서버 신호 발산

## 무엇을 했나

사고 모드가 답을 굶기는 버그(사고·답이 max_tokens 공유)를 A+B1로 수리:
- **A**(안전망): `finish_reason=length`를 trace.truncated로 표면화 — 원인 무관 모든 잘림 고지.
- **B1**(함정 제거): 사고ON + 명시적 작은 mt(0<mt<8192)면 이 요청만 8192로 대체 + 세션1회 토스트.
- **B3**(사고 길이 캡)은 스택 미지원으로 폐기(증거 — chat_template에 예산 로직 0).

## 배운 것(전이 가능)

### 1. 침묵 오버라이드의 해독제 = "고지된 조정"(bump + notice), 숨김도 거부도 아님

"사고 모드라 몰래 8192로 올린다"는 침묵 오버라이드 설계 냄새였다. 정답은 (a)그냥 올리기(침묵)도
(b)거부하고 사용자에 떠넘기기도 아닌, **올리되 세션1회 토스트로 알린다**. 자동성과 투명성을 동시에.
[[find-invariant-before-mechanism]]: A를 "잘림은 절대 침묵 안 함"이라는 *덮는 불변식*으로 두면 B1은
그 위의 특정 함정 제거로 자연히 정리된다(A가 B1 실패까지 잡는 안전망).

### 2. 안전망은 **서버 보고 신호**에 의존하고, 그 신호는 백엔드마다 다르다

A는 `finish_reason=length`에 의존한다. **vLLM(atom-spark)은 max_tokens를 하드캡하고 length를
보고**하지만, **MLX(8045)는 max_tokens=16을 하드캡하지 않아** 긴 생성이 나고 length가 안 뜬다.
→ 안전망 기능은 **실패 모드가 실제로 재현되는 플랫폼**에서 검증해야 한다. 브라우저 테스트가 기본
모델(MLX)로 돌아 A가 재현 안 돼 오해할 뻔했다 — 모델서버를 균일하다 가정하지 말 것.
[[compounding-vs-latent-axis]]의 "새 축"에 해당: 한 백엔드서 초록이 다른 백엔드 커버를 뜻하지 않음.

### 3. 검증 채널: 라이브 서버는 쿠키 로그인, 머신 토큰은 chat 불가

정밀 실측을 위해 라이브 서버(실 자격증명·`atom-spark` 호스트 해석)를 통해야 했다. **머신 토큰
(.dev/.api_token)은 /agents 열람은 되나 /chat은 401** — chat은 실 유저 principal 필요. `_provision_super`
(던짐 prefix `verify`/`shotfix`/`probe`만) + `/auth/login`(쿠키 `agentauth`) → httpx로 SSE 프로브가
재현 가능한 서버계약 verify가 됐다(verify_427_budget.py). 독립 프로브가 DB api_key 직접 읽으면 401
(실 키는 런타임 해석) — 앱 통로로 쳐야 한다.

### 4. bump는 배선 단일 지점(_resolve_wire_params)에 = 모델·경로 무관 균일

[[cache-function-inject-mutable]]와 결이 같다: 사고 바닥을 chat.py나 API별로 두면 새 호출부에서 샜다.
`_resolve_wire_params`(모든 ChatOpenAI 생성의 유일 통로)에 두니 chat·eval·a2a 전 경로가 공짜로 적용.
[[policy-at-the-chokepoint]].

## 흠집

- 브라우저 오버라이드 **모델 셀렉트가 가상화**라 vLLM(qwen36) 옵션이 뷰 밖→클릭 실패. 2회 시도
  후 중단(브라우저 토끼굴 가이드 준수). A의 FE 토스트 픽셀은 B1 렌더(동일 onTrace→message 경로)로
  대표하고 A 서버계약은 verify_427로 닫았다 — 픽셀 하나에 매달리지 않되 무엇을 무엇으로 대표했는지
  명시.
