# 031 — HIL 승인 게이팅 회고 (스펙 041, P5-a)

> 지배 스펙: `docs/spec/041-hil-approval-gating.md`. 관련 learning: [[040-real-infra-integration-catches-glue-and-deployment-drift]],
> [[038-adversarial-review-finds-what-invariants-miss]], [[037-floor-the-destructive-knob]],
> 회고 [[030-memory-backend-abstraction]].

## 무엇을 했나

- 가짜(seed status flip + seed-only row) 승인 큐를 **실 langgraph interrupt 게이트**로 교체. admin-승인 도구
  (`repo.merge`=github.merge_pr, `k8s.write`=kubernetes.scale)가 부수효과 **이전**에 `interrupt()`로 그래프를
  멈추고, 런타임 Approval(pending, checkpoint=thread_id)을 만들고, admin resolve가 `Command(resume=...)`로 재개.
- 체크포인터 = **AsyncPostgresSaver**(durable, 재시작·멀티워커 생존). 턴별 고유 thread_id(세션-안정 아님 —
  세션-안정+전체 히스토리는 `add_messages`가 중복 누적). 도구는 순수(interrupt payload만), DB 접근은 API 계층만.

## 검증을 *사다리*로 쌓은 것 (이번의 핵심)

안전 핵심 불변식("승인된 row 전엔 위험 도구 부수효과 0, 거부=무실행, 최대 1회 실행")을 **한 종류의 테스트로는
못 지킨다**. 세 rung을 쌓았다:

1. **게이트 시맨틱(verify_041, 인프라-경량):** 실 `build_tools`+ScriptedModel+MemorySaver로 interrupt 전
   calls_sink 0 / approve→1회 / reject→0 / read·무도구 회귀 / 정책 맵. 16/16. — *논리*를 박제.
2. **HTTP 통합(probe_041_chat_integration, 실 DB·실 AsyncPostgresSaver):** `/chat`→event_stream의 stream_mode
   튜플 파싱→`__interrupt__` 감지→`_create_approval`→approvals RBAC→`resume_approval` 재개·영속까지 **전 글루**.
   18/18. — *배선과 배포 상태*를 박제.
3. **적대 리뷰(서브에이전트 2회):** "승인 없이 부수효과가 나는 경로를 찾아라" — *불변식의 여집합*을 박제.

## rung마다 *다른 종류의 결함*이 나왔다

- **1차 적대 리뷰:** `/approvals/{id}/resolve`가 **인증만**(비-admin·머신토큰이 위험 도구를 승인 가능)이던
  진짜 홀 → `authz.require("approvals","resolve")` 추가, `probe_resolve_authz`로 HTTP 증명(admin→404, member→403,
  머신→401). 불변식 자가테스트는 "인가"를 아예 검사하지 않았다(상상 밖 범주, learning 038 재현).
- **HTTP 통합:** 처음엔 interrupt가 **전혀 안 났다**. 원인 = dev DB가 seed.py에 위험 도구가 추가되기 **전**에
  시드돼 있어 게이트 도구 미배선(seed는 `_empty`일 때만). 단위 게이트는 도구를 직접 주입하니 영원히 못 봤을
  **배포 갭** — 실 영속 상태를 태우는 통합 rung만이 잡았다(§7 빚 + setup 보정).
- **2차 적대 리뷰:** **Finding 1** — 한 턴에 위험 도구 ≥2면 다중 pending interrupt → chat이 `[0]`만 읽어 하나만
  Approval, resume이 interrupt-id 없이 실패→except가 삼켜 **status=approved인데 영영 미실행**. fail-closed(안전 무사)
  지만 오도 row. → 코드 floor(다중이면 승인 row 미생성·명시적 에러). **Finding 2**(sibling 안전도구 재실행 빚)는
  langgraph 1.x에서 재현 불가(완료 task write 캐시·미replay)로 **반증** → 빚 닫음.

## 작게 헛디딘 것

- **테스트 순서 artifact:** `run_once`가 chat+resolve를 한 번에 해서 "pause 시점" 검사가 이미 resolve된 상태를
  봤다(approved·영속 완료). chat과 resolve를 분리해 pause 시점을 정확히 찍어야 했다. 코드 버그 아님.
- **쿠키 Secure:** RBAC probe가 admin 로그인 204 후 후속 401. 원인 = CookieTransport 기본 `cookie_secure=true`라
  평문 ASGITransport에 쿠키 미재전송 — **하니스 한정**(프로덕션 HTTPS). `AUTH_COOKIE_SECURE=false`로 해결.
  "측정이 사용자 보고와 어긋나면 측정을 의심"(memory probe-deeper)을 코드 버그로 단정하기 전에 적용한 사례.
- **재개 시 모델 새 인스턴스 footgun:** resume_approval은 새 그래프·새 모델을 만든다. ScriptedModel을 idx 기반으로
  짜면 재개 시 idx=0이라 도구를 또 호출(무한루프). → 모델이 **ToolMessage 유무로 분기**(있으면 최종답)하게 해
  실 LLM 행동을 모사. 테스트 스텁이 프로덕션 재구축 경로를 정직히 반영해야 한다.

## 다음에 가져갈 것

- 부수효과를 막는 게이트엔 **세 rung 사다리**(시맨틱·실인프라 통합·적대)를 기본으로. 각 rung이 다른 결함을 잡는다.
- seed 변경은 기존 DB에 안 먹는다 — 위험 도구 같은 **배선 변경엔 idempotent 업서트/마이그레이션**을 같이.
- 푸시·머지 금지(사용자 브랜치 실테스트 예정). 브라우저 e2e(실 mlx)는 그 시점에.
