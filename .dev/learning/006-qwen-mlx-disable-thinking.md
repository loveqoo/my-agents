# 006 — Qwen(MLX) thinking 비활성으로 콘텐츠 누락 방지

날짜: 2026-06-19
type: reference

## 무엇이 문제였나
- 로컬 MLX의 `mlx-community/Qwen3.6-...`는 **thinking 모델**이라, 스트리밍 시 추론 토큰을 대량으로 뱉는다.
- 증상: `astream(stream_mode="messages")`에서 **5697 청크 중 실제 content는 21개**.
  긴 추론이 max_tokens를 소진하면 최종 content가 **0개로 누락**되어 빈 응답이 나옴.

## 해결
- `ChatOpenAI(..., extra_body={"chat_template_kwargs": {"enable_thinking": False}})`
- 적용 후 **5697 → 23 청크(content 20)** 로 정상화. MLX(OpenAI 호환)가 이 파라미터를 받아들임.
- `enable_thinking`을 top-level extra_body로 줘도 동작했으나, 표준은 `chat_template_kwargs` 안.

## 적용
- 로컬 MLX/Qwen 계열로 대화 노출 시 thinking을 끄는 것을 기본으로. (추론 노출이 필요하면 별도 채널)
- 관련: plan 001에 "Qwen thinking 출력" 리스크로 예고돼 있었음.
