# 415 — 첨부 후속 경화(스펙 404 OUT — codex 잔여 3축)

> 상태: **완료** · 2026-07-20 · 수치·P4 방향 개발자 승인(2026-07-20) · codex 적대 리뷰 P1 3건·P2 4건 봉합
> 발단: 스펙 404 codex 적대 리뷰 잔여(.dev/reviews/404-file-attach/codex.out P1 2건·P2 3건 중
> 미봉합분). nonce 펜스·추출 스레드격리+20s·스키마 캡(3/3만/200)·PDF 매직바이트는 404에서 봉합됨.

## 실측된 잔여 구멍(2026-07-20)

1. **전역 body limit 없음** — 수백 MB JSON이 전부 수신·파싱된 뒤에야 422(pre-parse 메모리 DoS).
   앱에 rate limit 전무. per-endpoint 캡(첨부 5MB raw·RAG PUT 선검사)만 점재.
2. **messages 개수·content 길이 상한 없음** — `ChatRequest.messages: list[ChatMessage]` 무제한.
   첨부 캡 3×3만자가 우연히 총합 역할(턴 전체 예산 계약 부재).
3. **첨부 턴 부수효과 도구 승인 강제 없음** — nonce 펜스는 구조 위조만 차단. 첨부 속 숨은 지시
   (간접 인젝션)가 승인 정책 없는 능력을 즉시 실행시키는 경로 잔존(broker/core.py `_gate` 주석에
   "백로그" 명시). **추가 발견**: 주입된 첨부는 세션 히스토리에 영속 → "이번 턴"만 강제하면
   다음 턴부터 같은 오염 히스토리로 강제가 풀리는 재생 구멍.

## 승인된 수치(사용자 가시 한계 — 2026-07-20 개발자 승인)

- 전역 body **2MB** · 업로드 라우트(`/chat/attachments`)만 **6MB**(파일 5MB+multipart 오버헤드)
- `messages` 최대 **200개** · `content` 개당 **5만자**
- 업로드 rate limit **분당 10회/유저**

## 구현

- **P1 전역 body limit 미들웨어**: ASGI 층 — Content-Length 선검사(빠른 거절) + **raw receive
  바이트 누적 실측**(스푸핑 무력 — learning 041 cap-raw-source) 초과 시 413. 업로드 라우트만
  상한 6MB 오버라이드. 명확한 한국어 오류 메시지.
- **P2 턴 예산 계약**: 스키마 상한(messages ≤200, content ≤5만자) + "턴 총합" 명문화(첨부 총합
  9만자 + user 메시지 5만자 = 최대 14만자/턴, 히스토리는 기존 depth 상한이 관할) — 주석·스펙에
  계약 명시.
- **P3 업로드 rate limit**: `/chat/attachments` per-user 인메모리 토큰버킷(분당 10회) → 초과 429.
  단일 인스턴스 전제(개인 플랫폼 — k8s 멀티 인스턴스는 백로그 별항).
- **P4 첨부 유래 턴 승인 강제**: "이번 요청 첨부 있음 **또는** 히스토리에 첨부 펜스 마커 존재"를
  `attachment_context` 플래그로 판정 → 도구 승인 리졸버 관문([[policy-at-the-chokepoint]] —
  `resolve_tool_approval` 공유 지점 + broker `_gate`)에서 **정책 없는 능력도 승인 요구**로 승격.
  읽기 전용으로 명시 분류된 능력(RAG 검색·메모리 검색/목록)은 면제. 입구는 grep 전수 열거
  (learning 236 — 기억 아닌 grep으로).

## OUT

- 프록시/인프라 층 body limit(nginx 등) — 배포 미정의(k8s 백로그와 합류). 앱 층이 1차 방어.
- rate limit의 다중 인스턴스 공유(redis 등) — 단일 인스턴스 전제 명시.
- 모델 차원 인젝션의 완전 차단(불가능) — P4는 부수효과 실행 경로 봉합이지 인지 차단 아님.
- 히스토리 포함 모델별 컨텍스트 예산 자동 조절 — 기존 depth 상한 유지, 별도 스펙.

## 완료 기준 — 달성(실측)

- [x] 2MB 초과 JSON body → 413(Content-Length 선검사 + chunked raw 누적 실측 둘 다), 업로드 6MB 경계.
- [x] messages 201개·content 15만자·현재 턴 5만자 초과 → 422. 경계값(200개·5만자) 통과.
- [x] 업로드 11회째 → 429, 윈도 스윕으로 회복.
- [x] 첨부 턴 + 승인 정책 없는 MCP/agent cap → 승인 interrupt(브로커·그래프-tools 양경로). RAG·메모리
      읽기 면제. 히스토리 재생 턴(첨부 없는 후속·A2A 서빙)도 강제 유지.
- [x] verify_415 **25/25** + verify_404 무회귀 + make test 91/0/0.
- [x] **codex 적대 리뷰** P1 3건·P2 4건 전부 봉합(아래).

## codex 적대 리뷰 결과 — "보장 목록의 여집합"이 실입구를 짚음

**P1(실구멍) 3건 — 전부 봉합**:
1. **A2A 서빙 재생 우회**(최대 구멍): 악성 첨부를 로컬 채팅서 심어 영속 → 같은 에이전트 A2A
   엔드포인트로 그 contextId 재생 → 대화는 복원되나 도구는 `force_approval=False`로 빌드돼 승인 없이
   실행. 메인 채팅만 마커를 검사하고 A2A 서빙 입구를 빠뜨림([[policy-at-the-chokepoint]] 위반).
   → `prepare_serve_turn`이 재생 대화 마커로 판정 후 `_build_serve_tools`에 force_approval 관통.
2. **레거시 pending Approval 재개**: 415 배포 전 pending 행은 스탬프 없어 재개 시 강제 해제.
   → 스탬프 부재 시 세션 대화 마커 스캔으로 보강(선행 턴 포착, 첫 턴 미영속분은 유한 잔여 명시).
3. **브로커 강제 payload가 args 숨김**: `args:{}`로 승인자가 무엇을 승인하는지 못 봄(정보 없는 승인).
   → `_redact_args`로 마스킹된 인자 노출(구조 보존·비밀만 가림).

**P2(경계) 4건 — 봉합**:
- 5만자 우회(끝에 assistant 붙여 마지막-위치 검사 회피) → **마지막 user 메시지**로 검사(마커 echo 면제).
- rate dict 무한 증가 → 호출당 전체 키 스윕(빈 키 삭제).
- body-limit 이중 start(스트리밍 라우트) → `app_started` 가드로 재작성 억제 + RAG 경로 **세그먼트 매칭**
  (`/documentsXYZ` 부분문자열 오탐 제거).
- 무제한 문자열 필드(formId·version) → max_length 200/80. overrides·form.values dict는 전역 2MB가 관할(명시).

verify_415에 E2f(우회)·E4c′(마스킹 인자)·E7(A2A 재생 force 배선) 추가로 회귀 그물 확장.
