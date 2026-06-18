# 004 — AskUserQuestion에 CJK는 \u 이스케이프 말고 직접 작성

날짜: 2026-06-19
type: reference

## 무엇이 잘못됐나
- AskUserQuestion 호출 시 한국어를 `\uXXXX`로 이스케이프한 raw JSON 문자열로 보냈다가
  "could not be parsed as JSON"으로 **두 번 연속 실패**했다.

## 그래서 규칙
- AskUserQuestion(및 도구 입력 일반)의 문자열 필드에 한국어 등 비ASCII는
  **리터럴 UTF-8 문자로 그대로 작성**한다. `\uXXXX` 수동 이스케이프 금지.
- 허용 이스케이프는 `\n`, `\t`, `\"`, `\\` 정도.
- 구조화된 파라미터(questions 배열)를 **정상 JSON 값**으로 넘기고, raw 문자열을 손으로 조립하지 않는다.

## 적용
- 질문/옵션 텍스트에 한글을 쓸 때 그냥 한글로 쓴다. 길이가 길어도 이스케이프하지 않는다.
