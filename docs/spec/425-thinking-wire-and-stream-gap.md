# 425 — thinking 배선 이중화 + 스트리밍 reasoning 간극 판정

> 상태: **완료(앱 측)·서버 확인 대기**(2026-07-21) · 발단: 스펙 424 검증 중 개발자 질문
> "thinking 모드로 검증했나" → 라이브 사고 패널 불발 → 계단식 프로브로 근인 2개 분리.

## 발견 1 — 앱 결함(수리): bool 파라미터 배선이 chat_template_kwargs 단일
스펙 411의 통일 배선이 `extra_body.chat_template_kwargs.enable_thinking`만 실었는데, 현행
rapid-mlx는 **root 키(enable_thinking)만 인식**(실측: 비스트림 root=reasoning_content 발화,
chat_template_kwargs=무시). 즉 411 이후 라이브 thinking이 조용히 꺼져 있었고, verify_410/413이
fake-reasoning 모델이라 그물이 못 봤다(fake-green 간극). **수리=이중 배선**(root+chat_template_
kwargs 둘 다 — vLLM계·rapid-mlx 양쪽 호환, 미지원 필드는 서버가 무시). verify_411 24/24·410 14/14.

## 발견 2 — 서버 간극(우리 코드 밖): 스트리밍은 reasoning 미릴레이
파서는 활성(개발자 확인 + 비스트림 실증). 그러나 **스트리밍에서는** 전 변형(root/ctk/둘 다)에서
reasoning 델타 0, 본문이 `\n\n`으로 시작(사고 블록을 서버가 걷되 릴레이 안 하는 잔흔). 앱은
스트리밍 경로라 사고가 도착 자체를 안 함. 410 당시 스트리밍 동작했으므로 서버 갱신/재시작에서
동작 변화로 추정 — **rapid-mlx의 스트리밍 reasoning 지원(버전·옵션) 확인 필요(개발자 액션)**.

## 프로브 대장(전부 앱 자격증명·같은 채널)
| 프로브 | 결과 |
|---|---|
| 비스트림 + root enable_thinking | reasoning_content **발화** |
| 비스트림 + chat_template_kwargs | 미발화 |
| 스트림 + root/ctk/둘 다 | 델타 0 · `<think>` 원문도 없음 · 본문 선두 `\n\n` |
| 앱 SSE(수리 후) | reasoning 프레임 0(서버 간극으로 설명) |

## 잔여
- 서버가 스트리밍 reasoning을 켜면: 모델 params(enable_thinking) 활성 후 verify-424 스크립트의
  사고 패널 단언(①-t)으로 라이브 확정 1회. 임시로 켰던 모델 params는 원상({}) 복원 완료.
