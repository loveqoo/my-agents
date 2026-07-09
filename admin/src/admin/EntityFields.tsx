/* 엔티티 직렬화 텍스트 뷰(스펙 254→255 공용화) — "key: value" 라인 형식이면 값 있는 필드만
   고정폭 2열 표로, 빈 필드는 이름만 한 줄(빈 값도 자리 차지 금지 — 246 문법). 검색 시험
   (RetrievalTestPanel)과 플레이그라운드 인스펙터 RAG 히트가 공유(두 벌=드리프트). */

export function parseEntityText(text: string): { rows: [string, string][]; empty: string[] } | null {
  const lines = text.split('\n').filter((l) => l.trim().length > 0)
  if (lines.length < 2) return null
  const rows: [string, string][] = []
  const empty: string[] = []
  for (const l of lines) {
    const m = l.match(/^([\w.]+):\s*(.*)$/)
    if (!m) return null // 한 줄이라도 형식 밖이면 원문 그대로(문서 청크 등)
    if (m[2].trim()) rows.push([m[1], m[2].trim()])
    else empty.push(m[1])
  }
  return rows.length ? { rows, empty } : null
}

export function EntityFields({ rows, empty, size = 13 }: { rows: [string, string][]; empty: string[]; size?: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {rows.map(([k, v]) => (
        <div key={k} style={{ fontSize: size, display: 'flex', gap: 8 }}>
          <span style={{ color: 'var(--color-text-tertiary)', minWidth: 118, flex: 'none', fontFamily: 'var(--font-family-code)', fontSize: size - 1 }}>{k}</span>
          <span style={{ color: 'var(--color-text-secondary)', overflowWrap: 'anywhere' }}>{v}</span>
        </div>
      ))}
      {empty.length > 0 && (
        <div style={{ fontSize: size - 1, color: 'var(--color-text-quaternary)', marginTop: 2 }}>
          빈 필드: {empty.join(' · ')}
        </div>
      )}
    </div>
  )
}
