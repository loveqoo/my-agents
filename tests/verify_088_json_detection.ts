/* 스펙 088 검증 — 전체-JSON 판별 게이트 매트릭스(순수, 브라우저 불필요).
   핵심 불변식: "전체 응답이 JSON *문서*(object/array)"일 때만 json 경로.
   42·true·"hi"·null은 유효 JSON이어도 markdown 경로(거짓양성 차단).

   Node 24의 타입 스트리핑으로 .ts를 직접 실행:
     node tests/verify_088_json_detection.ts */
import {
  detectFormat,
  jsonTooBigForTree,
  JSON_TREE_MAX_CHARS,
  exceedsRenderBudget,
  RENDER_BUDGET_MAX,
} from '../admin/src/playground/messageFormat.ts'

let fails = 0
function check(cond: boolean, msg: string): void {
  console.log((cond ? '  ok  ' : ' FAIL ') + msg)
  if (!cond) fails++
}

console.log('[J] json 경로 — object/array 문서만')
check(detectFormat('{"a":1}').kind === 'json', 'J1 object → json')
check(detectFormat('[1,2,3]').kind === 'json', 'J2 array → json')
check(detectFormat('  \n {"a":1}  \n ').kind === 'json', 'J3 공백 둘러싼 object → json')
const r = detectFormat('{"a":{"b":[1,true,null]}}')
check(r.kind === 'json' && (r.value as any).a.b[1] === true, 'J4 중첩 파싱값 보존')

console.log('\n[M] markdown 경로 — 거짓양성 차단')
check(detectFormat('42').kind === 'markdown', 'M1 number → markdown')
check(detectFormat('true').kind === 'markdown', 'M2 bool → markdown')
check(detectFormat('"hi"').kind === 'markdown', 'M3 string-literal → markdown')
check(detectFormat('null').kind === 'markdown', 'M4 null → markdown')
check(detectFormat('').kind === 'markdown', 'M5 empty → markdown')
check(detectFormat('   \n  ').kind === 'markdown', 'M6 공백만 → markdown')
check(detectFormat('# 제목\n\n**굵게** 그리고 목록\n- a\n- b').kind === 'markdown', 'M7 markdown 텍스트 → markdown')
check(detectFormat('{ this is not json').kind === 'markdown', 'M8 깨진 json → markdown')
check(detectFormat('결과는 다음과 같습니다: {"a":1}').kind === 'markdown', 'M9 문장 안 json(시작 아님) → markdown')
check(detectFormat('```json\n{"a":1}\n```').kind === 'markdown', 'M10 펜스 감싼 json → markdown(펜스는 markdown이 그림)')
check(detectFormat('{"a":1} 뒤에 꼬리 텍스트').kind === 'markdown', 'M11 object 뒤 꼬리 → markdown(전체 문서 아님)')

// codex F1·F4 회귀 가드: 트리 적합성 게이트. 거대/정밀도위험은 트리 대신 원문 pre로 폴백.
console.log('\n[T] jsonTooBigForTree — 거대/큰정수 폴백')
check(jsonTooBigForTree('{"a":1}') === false, 'T1 평범한 JSON → 트리 OK')
check(jsonTooBigForTree('{"a":' + '0'.repeat(JSON_TREE_MAX_CHARS) + '}') === true, 'T2 길이 상한 초과 → 폴백')
check(jsonTooBigForTree('{"id":9007199254740993}') === true, 'T3 16자리+ 정수 런(정밀도 손실) → 폴백')
check(jsonTooBigForTree('{"id":999999999999999}') === false, 'T4 15자리 정수(안전 범위·16자리 미만) → 트리 OK')
check(jsonTooBigForTree('{"id":"9007199254740993"}') === true, 'T5 문자열 속 16자리(거짓양성=안전 측) → 폴백')

// codex F1 covering 가드: parse·markdown 비용 지점 *앞*에서 거대 입력을 차단해야 한다.
// MessageContent가 exceedsRenderBudget를 detectFormat보다 먼저 호출하므로, 이 임계 함수가
// 예산 초과를 올바로 판정해야 가드가 덮인다(검사지점=비용지점 앞 단언).
console.log('\n[B] exceedsRenderBudget — parse 전 차단')
check(exceedsRenderBudget('{"a":1}') === false, 'B1 평범한 입력 → 예산 내(정상 경로)')
check(exceedsRenderBudget('x'.repeat(RENDER_BUDGET_MAX)) === false, 'B2 임계 동일 → 예산 내(경계)')
check(exceedsRenderBudget('x'.repeat(RENDER_BUDGET_MAX + 1)) === true, 'B3 임계 초과 → 예산 밖(parse 전 직행)')
// 트리캡(50k) < 렌더예산(1MB): 둘은 별개 관심사(트리 노드폭주 vs parse/파싱 비용).
check(JSON_TREE_MAX_CHARS < RENDER_BUDGET_MAX, 'B4 트리캡 < 렌더예산(관심사 분리)')

if (fails) {
  console.log(`\nFAILED (${fails})`)
  process.exit(1)
}
console.log('\nALL GREEN (088 detection)')
