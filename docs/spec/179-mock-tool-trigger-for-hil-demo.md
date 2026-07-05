# 179 — mock 모델 도구 트리거(HIL 승인 대화 실습)

## 배경·목표
mock 챗 모델(`mock_remote.py`)은 **도구 호출을 미지원**(평문만) — 그래서 승인 게이트 대상 도구
(`local-tools.delete_record`, approval.required)를 **플레이그라운드 대화로 트리거할 수 없었다**.
실모델(외부 키) 없이 HIL 승인 흐름을 대화로 실습할 방법이 없다.

**목표**: mock에 **개발용 도구 트리거**를 달아, 바인딩된 도구가 있고 마지막 user 메시지가 트리거
문구에 맞으면 그 도구의 `tool_call`을 결정적으로 내게 한다. 그러면 플레이그라운드에서 실제로
`delete_record` 호출→interrupt→승인 대기가 뜨고, **어드민 승인·본인(self) 승인**을 대화로 경험한다.

## 비목표
- mock을 범용 도구 추론기로 만들지 않는다(트리거 맵에 등록된 도구만, 결정적 규칙).
- 실 LLM 툴콜 품질 재현 아님(데모/실습용 스텁).

## 설계
`mock_remote.py`의 `remote_v1_chat_completions`(스트림·비스트림 모두):
1. **재개 후 턴 감지**: messages에 `role=="tool"`가 있으면 → 평문(요약)으로 응답(도구 실행 뒤 마무리
   턴). 이게 없어야 무한 tool_call 루프를 막는다.
2. **트리거 매치**: 요청 `tools`(바인딩된 도구)에 트리거 맵의 도구가 있고, 마지막 user 텍스트가 그
   도구의 키워드에 맞으면 → 그 도구의 `tool_call` emit(OpenAI 계약: 비스트림=message.tool_calls +
   finish_reason "tool_calls", 스트림=index 기반 delta 청크).
   - `_TOOL_TRIGGERS = {"delete_record": (키워드["삭제","지워","제거","delete"], record_id 추출)}`.
   - 인자 추출 실패 시 기본값("rec-001").
3. **그 외**: 기존 평문(`_mock_reply`) 그대로 — 평상 채팅 무영향(트리거 무매치·도구 미바인딩).

**대화 흐름(그래프)**: 턴1 messages=[system,user] → 트리거 → tool_call → 그래프가 tool 노드로 가나
delete_record는 approval.required라 **실행 전 interrupt**(승인 대기, 부수효과 0). 승인·재개 →
tool 실행 → tool 결과가 messages에 → 모델 재호출(role=tool 존재 → 평문 요약).

## 본인(self) 승인 실습 — 검증 완료
member 계정(`shotfix_selfdemo@example.com`) + 데모 에이전트(`self-approval-demo`, public,
`config.toolPolicy` = delete_record approver=self)로 e2e 검증(`verify-self-approval.mjs`): member
로그인→"레코드 삭제"→승인 대기→승인 페이지에 **본인 것**이 "👤 본인 승인" 태그로 뜨고→본인이 승인
(403 아님)→서버 재개. 슈퍼유저는 is_privileged라 self 분기를 안 타므로 member 계정이 필수.

**부수 버그 수정(태그 하드코딩)**: 승인 태그가 approver 무관하게 "관리자 승인" 하드코딩이었다(모델엔
`approver` 있으나 ApprovalOut·서러라이저·프론트 Approval 타입에 미배선). approver를 끝까지 배선해
태그를 데이터 기반으로(self=파랑 "본인 승인", admin=보라 "관리자 승인"). 페이지 부제도 "관리자 승인
작업"→"승인 작업 — 관리자/본인" 중립화.

## 승인 두 종류 실습
- **어드민 승인**: `delete_record` 기본 approver=admin(mock_mcp 메타). local-tools 물린 에이전트로
  "레코드 삭제" → 승인 페이지(관리자)에서 승인.
- **본인(self) 승인**: 에이전트 편집기에서 `delete_record` 오버라이드 approver=self(177 P2) → 같은
  대화가 요청 소유자 본인 승인 대상. 같은 승인 페이지에 뜨고 본인이 승인(`_may_resolve` self).
  (두 종류가 같은 큐에 뜨되 approver로 인가 분기 — 별 UI 불요.)

## 검증(완료 조건)
- **단위**: mock에 tools=[delete_record]+user "r1 삭제" → 응답이 tool_call(name=delete_record,
  args.record_id 채워짐). tools 없거나 트리거 무매치 → 평문(무회귀). messages에 role=tool 있으면 →
  평문(재개 요약). 스트림·비스트림 둘 다.
- **회귀**: 기존 mock 평문 계약(스펙 024) 무회귀 — 트리거 무매치 채팅은 기존과 동일.
- **e2e(브라우저, 타자 검증)**: 플레이그라운드에서 local-tools 에이전트에 "레코드 삭제" → "승인 대기"
  프레임 + 승인 페이지에 pending 1건(자물쇠 아이콘) → 승인 → 도구 실행/최종 답변. approver=self로
  바꿔 본인 승인도 동일 확인.

## 단계
- **P1**: mock 트리거 구현(mock_remote.py) + 단위 검증. ✅
- **P2**: 플레이그라운드 e2e(어드민 승인). ✅
- **P3(실사용서 발견)**: 승인 후 **요청자 채팅 자동 갱신**. ✅

## P3 — 승인 후 요청자 채팅이 멈춰 있던 버그(실사용 제보)
2브라우저 실사용(브1 삭제요청→브2 승인→브1 계속 멈춤)에서 드러남. 백엔드는 승인 시 서버사이드로
재개해 결과를 세션에 영속하나(`resume_approval`→`_persist`), **대기 중 요청자 채팅엔 라이브 push가
없어**(§7 빚) "승인 대기"에 멈춰 있었다(데이터 소실 아님 — 세션 재열람하면 보임).

**수정(폴링)**:
- `api.ts`: 승인 프레임(`{text, approval}`)의 `approval` id를 `onApproval` 콜백으로 표면화
  (기존엔 `text`만 토큰으로 쓰고 id는 버렸다).
- `Playground.tsx`: `onApproval`이 승인 대기 상태를 잡아 `listApprovals`를 2.5s 주기 폴링. 해소되면
  그 세션 메시지를 다시 불러 완료 턴을 채팅에 반영(최대 ~2.5분 후 조용히 포기 — 세션 재열람 안내).
- **레이스 주의**: `resolve`가 status를 먼저 approved로 커밋한 뒤 서버사이드 재개·persist를 하므로,
  status만 보면 persist 전에 **빈 세션**을 그린다. **세션 메시지 수 증가(baseline 대비)**를 함께
  확인해 persist 완료 시점에만 반영.

**검증**: `tests/browser/verify-approval-resume-visibility.mjs` — 2컨텍스트로 브1 요청→브2 승인→
브1이 폴링으로 완료 턴 자동 표시(승인 대기·빈세션 사라지고 재개 응답+도구 실행 1 mcp 노출).

**추가 버그(실사용 제보) — 승인 대기 중 입력 순서 뒤바뀜**: 대기 중 사용자가 새 턴을 입력하면, 그
턴이 **먼저 완료·저장**되고 대기 턴은 승인 후 저장돼(저장시각 순 재로드) 대화가 뒤바뀐다. 그래프는
그 턴에서 멈춰 있으므로 **승인 대기 중엔 입력을 차단**(Sender disabled + "승인 대기 중 — 승인/거부 후
이어서 입력하세요" 안내, `send`도 가드). 검증 `verify-approval-input-blocked.mjs`.
