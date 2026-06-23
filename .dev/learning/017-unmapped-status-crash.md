# 017 — 자유 문자열을 하드코딩 맵으로 조회하면 렌더가 통째로 죽는다

날짜: 2026-06-24
맥락: 015 vectorTable 편집 시 rows/status 보존(P1) 회귀 E2E가 60s 타임아웃.
      "행 클릭"에서 시드된 행을 영영 못 찾음. /blocks API엔 데이터가 분명히 있었다.

## 증상
- 진단 테스트로 `벡터` 탭 진입 후 콘솔/페이지 에러를 캡처: `<code>` 텍스트 0개,
  스크린샷 백지, `tr` 0개. 다른 탭(persona/memory/mcp)은 정상.
- `pageerror`: **`Cannot read properties of undefined (reading 'tag')`** —
  `<DataTable>` 컴포넌트에서 발생, BlocksView embedding 컬럼 렌더.

## 루트 원인
```ts
const s = VECTOR_STATUS[r.status!]      // 맵에 없는 status면 undefined
return <Tag color={s.tag}>{s.label}</Tag>  // undefined.tag → throw → 행 렌더 중 throw
```
- `VECTOR_STATUS`엔 `synced/indexing/stale`만 있는데 백엔드 `status`는
  **enum이 아니라 자유 문자열**(`schemas.py: status: str = "synced"`).
- 맵에 없는 값(테스트가 seed한 `syncing`, 또는 미래의 임의 값)이 오면
  렌더 함수가 throw → React가 **DataTable 서브트리 전체를 언마운트**(백지).
- 그래서 "행을 못 찾는" 증상으로 위장됐다. 실제는 페이지 크래시.
- 같은 패턴이 `MCP_STATUS` 컬럼·상세 드로어에도 있었다(잠재 동일 버그).

## 고친 방법
폴백 헬퍼로 일원화 — 맵에 없으면 raw 문자열을 default Tag로:
```ts
function statusTag(map: Record<string, StatusMeta>, status?: string | null) {
  const s = status ? map[status] : undefined
  if (s) return <Tag color={s.tag}>{s.label}</Tag>
  return <Tag color="default">{status ?? '—'}</Tag>
}
```
컬럼·상세 드로어의 모든 `MAP[status].tag` 접근을 이걸로 교체.

## 배운 것
- **외부/DB 값으로 객체를 인덱싱한 뒤 곧바로 속성 접근하지 마라.** 특히 렌더 경로.
  값 도메인이 코드 상수와 분리돼 있으면(자유 문자열 컬럼) 언제든 미스가 난다 → 폴백 필수.
- **렌더 throw는 "데이터 없음"으로 위장한다.** E2E가 "요소를 못 찾음"으로 타임아웃하면
  단정 짓지 말고 `pageerror`/console을 먼저 캡처하라. (관련: [[016-verify-ui-before-test-guide]])
- enum이 아닌 status 컬럼은 UI 렌더와 **암묵적으로 결합**돼 있다. 한쪽만 값을 추가하면 깨진다.
- 가드 `MAP[x] ? ... : null`는 크래시는 막지만 **값을 통째로 숨긴다**(상세 드로어가 그랬다).
  폴백 렌더가 더 정직하다 — 알 수 없는 값도 사용자에게 보여준다.

관련: [[012-runtime-config-single-source]] (값의 단일 출처), [[013-keep-the-step-header]].
