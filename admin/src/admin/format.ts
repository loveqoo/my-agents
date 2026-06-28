/* 표시용 시각 포맷터. 백엔드는 _iso()로 ISO8601(마이크로초·+00:00)을 그대로 내려주는데
   그걸 날것으로 렌더하면 "2026-06-28T11:19:59.317619+00:00"처럼 깨져 보인다(스펙 055 후속).
   - ISO면: 오늘=시:분, 올해=M월 D일, 그 외=YYYY. M. D.
   - 파싱 불가(목업의 '32m ago'·'Yesterday' 같은 친화 문자열)면 그대로 통과.
   - 빈 값은 ''. */
export function fmtTime(v?: string | null): string {
  if (!v) return ''
  const t = Date.parse(v)
  if (Number.isNaN(t)) return v // 이미 사람이 읽는 문자열(목업 등) — 그대로.
  const d = new Date(t)
  const now = new Date()
  if (d.toDateString() === now.toDateString())
    return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
  const opts: Intl.DateTimeFormatOptions =
    d.getFullYear() === now.getFullYear()
      ? { month: 'long', day: 'numeric' }
      : { year: 'numeric', month: 'numeric', day: 'numeric' }
  return d.toLocaleDateString('ko-KR', opts)
}
