# 343 — 첨부 후속 경화(스펙 415)

## 발단
스펙 404(플레이그라운드 파일첨부)의 codex 적대 리뷰가 남긴 잔여 3축 — ①전역 body limit 부재
(pre-parse 메모리 DoS) ②턴 예산 계약 부재 ③첨부 턴 부수효과 도구 승인 강제 부재(간접 인젝션).
수치(2MB/6MB·200개·5만자·분당10회)와 P4 방향(승인 강제)을 개발자 승인받고 착수.

## 한 일
- P1 전역 body limit(ASGI 미들웨어) · P2 턴 예산(스키마+입구 캡) · P3 업로드 rate limit ·
  P4 첨부 유래 턴(히스토리 재생 포함) 부수효과 도구 승인 강제(그래프-tools+브로커 양경로).
- verify_415 25/25 + codex 적대 리뷰 P1 3건·P2 4건 봉합.

## 배운 것

### 1. 새 횡단 방어는 **입구를 grep 전수**하라 — 자가 열거는 샌다
P4 승인 강제를 메인 채팅 경로에 넣고 "됐다" 했으나, codex가 **A2A 서빙 재생 경로**를 짚었다:
악성 첨부를 로컬 채팅서 심어 영속 → 같은 에이전트의 A2A 엔드포인트로 그 contextId 재생 → 대화는
복원되나 도구는 `force_approval=False`로 빌드돼 승인 없이 실행. [[installed-guard-isnt-covering-guard]]
그대로 — 가드 "설치"≠"전 입구 커버". [[policy-at-the-chokepoint]]의 교훈(횡단 정책은 관문 한 곳)을
알면서도 **입구가 둘(chat·a2a_serve)인데 하나만** 판정했다. 방어를 걸 땐 그 자원을 만지는 입구를
grep으로 닫힌 집합 열거(learning 236) — "메인 경로 하나"는 늘 덜 세었다는 신호.

### 2. ASGI body limit은 **예외가 아니라 send-재작성**으로
raw 수신 누적이 상한 초과 시 예외를 던져 앱을 뚫는 방식은 안 된다 — FastAPI가 body 파싱 중 예외를
전부 400("error parsing the body")으로 삼킨다(실측). 대신 ①초과 시점에 receive를 `http.disconnect`로
접어 앱이 더 못 읽게 하고 ②앱이 뭘 응답하든 send 측에서 413으로 **재작성**한다. 단 앱이 이미
응답을 시작(response.start)한 뒤면 이중 start 금지라 재작성 불가 — `app_started` 가드로 스트리밍
라우트를 방어. "예상 실패 경로가 프레임워크에 삼켜지지 않는가"를 실측으로 확인(추측 금지).

### 3. 캡은 **가시 한계 = 사용자 승인**, 구조 캡 = 자동
messages 200개·현재 턴 5만자는 **사용자 가시 한계**라 승인 사항([[product-limits-need-explicit-approval]]).
반면 content 15만자(주입 echo 수용)·formId 200자는 **구조 DoS 방어**라 구현 재량. 둘을 섞으면 안 된다 —
5만자(가시 계약)를 스키마 캡으로 착각하면 주입 echo(≤14만자 재생)가 깨진다. **가시 한계는 입구에서
강제·구조 캡은 스키마에서**, 그리고 "마지막 user 메시지"로 검사해야 끝에 assistant 붙이는 우회를 막는다.

### 4. 강제 승인도 **정보에 근거한 승인**이어야
브로커 강제 payload에 `args:{}`만 실어 "안전측"이라 여겼으나, codex가 "승인자가 무엇을 승인하는지
못 본다"고 짚었다 — 악성 첨부가 유도한 위임/도구 호출을 사용자가 일반 실행으로 오인 승인한다.
`_redact_args`로 **마스킹된 인자를 노출**(구조는 보이고 비밀만 가림)해야 승인이 의미를 갖는다.
"안전측 비노출"이 오히려 승인 품질을 죽이는 역설 — 승인 게이트의 목적은 차단이 아니라 *판단*이다.

### 5. 마이그레이션 잔여는 **줄이고 명시**(정직한 경계)
415 배포 전 pending Approval은 스탬프가 없어 재개 시 강제가 풀린다. 세션 대화 마커 스캔으로 선행
턴을 포착해 구멍을 줄였으나, 첫 첨부 턴 자체의 주입 메시지는 interrupt 시점 미영속(체크포인트만)이라
스캔이 못 본다 — **유한 잔여**(배포 시점 pending 행 한정)를 스펙에 명시했다. 완전 봉합이 비싸면
축소+명시가 정직([[complement-attack-can-be-honest-boundary]]).

## 자산화 후보(관련)
[[installed-guard-isnt-covering-guard]] [[policy-at-the-chokepoint]] [[adversarial-review-before-destructive-ship]]
[[product-limits-need-explicit-approval]] [[cap-the-raw-source-not-the-buffer]] [[use-codex-for-adversarial-verification]]
