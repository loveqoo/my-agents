/* 스펙 088 — assistant 응답의 표시 형식 추론(순수 로직, JSX 없음).
   "전체 응답이 JSON 문서"일 때만 JSON으로 본다. 형식 추론은 스트림이 끝까지
   와야 확정 가능하므로(부분 버퍼로는 못 함) 호출측이 완료 시점에만 부른다 —
   이 모듈은 그 완성된 문자열을 받아 판별만 한다.

   거짓양성 차단: `42`·`true`·`"hi"`는 유효 JSON이어도 *문서*가 아니라 markdown 경로로.
   즉 trim이 `{`/`[`로 시작 + parse 성공 + 결과가 object/array 일 때만 json.

   Node 24의 타입 스트리핑으로 tests/verify_088_json_detection.ts가 직접 import해
   브라우저 없이 매트릭스를 단언한다(erasable 문법만 사용). */

export type DetectResult =
  | { kind: 'json'; value: unknown }
  | { kind: 'markdown' }

export function detectFormat(text: string): DetectResult {
  const trimmed = text.trim()
  // 전체-JSON 문서만: object/array 리터럴로 시작해야 시도조차 한다.
  if (trimmed.length === 0) return { kind: 'markdown' }
  const head = trimmed[0]
  if (head !== '{' && head !== '[') return { kind: 'markdown' }
  try {
    const value = JSON.parse(trimmed)
    // typeof null === 'object' 이지만 head 게이트상 여기 도달 불가. 방어적으로 제외.
    if (value !== null && typeof value === 'object') return { kind: 'json', value }
    return { kind: 'markdown' }
  } catch {
    return { kind: 'markdown' }
  }
}

// 트리를 *대화식으로* 그리기엔 부적합한 JSON(codex F1·F4):
//  - 너무 큰 입력 → 전 노드를 React 요소로 만들면 메인스레드 프리즈.
//  - 16자리+ 정수 런 → JSON.parse가 정밀도를 잃어(2^53 초과) 디버그 콘솔이 *틀린 ID/타임스탬프*를
//    표시. 문자열 안 숫자나 긴 소수도 보수적으로 걸려 안전하게 원문 pre로 폴백(거짓양성=안전 측).
// 둘 중 하나면 트리 대신 원문 verbatim 블록으로(정밀도 보존·렌더 폭주 방지).
export const JSON_TREE_MAX_CHARS = 50_000
const BIG_INT_RUN = /[0-9]{16,}/

export function jsonTooBigForTree(text: string): boolean {
  return text.length > JSON_TREE_MAX_CHARS || BIG_INT_RUN.test(text)
}

// 렌더 예산 상한(codex F1, "가드를 비용 지점 앞으로"). detectFormat은 jsonTooBigForTree를
// 보기 *전에* 이미 JSON.parse(전체)를 동기 실행하고, markdown 경로는 remark가 전체를 파싱한다.
// 즉 트리캡만으론 거대 입력의 parse/파싱 비용을 못 막는다 — 비용 발생지점 *앞*에서 차단해야
// covering. 이 한도를 넘으면 parse도 markdown도 시도하지 않고 원문 캡 블록으로 직행한다.
// (1MB: 평범한 응답은 KB 규모라 무관, 이 이상은 어떤 경로든 메인스레드를 막을 만큼만 가른다.)
export const RENDER_BUDGET_MAX = 1_000_000

export function exceedsRenderBudget(text: string): boolean {
  return text.length > RENDER_BUDGET_MAX
}
