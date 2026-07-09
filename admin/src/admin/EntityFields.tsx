/* 엔티티 직렬화 텍스트 뷰(스펙 254→255 공용화) — "key: value" 라인 형식이면 값 있는 필드만
   고정폭 2열 표로, 빈 필드는 이름만 한 줄(빈 값도 자리 차지 금지 — 246 문법). 검색 시험
   (RetrievalTestPanel)과 플레이그라운드 인스펙터 RAG 히트가 공유(두 벌=드리프트). */

export function parseEntityText(text: string): { rows: [string, string][]; empty: string[] } | null {
  const lines = text.split('\n')
  const rows: [string, string][] = []
  const empty: string[] = []
  let started = false
  let contIdx = -1 // 값이 이어질 수 있는 직전 필드(rows 인덱스) — 멀티라인 값 이어붙이기용
  for (const raw of lines) {
    if (raw.trim().length === 0) continue // 빈 줄은 건너뜀(값 사이 문단 구분은 접음)
    const m = raw.match(/^([\w.]+):\s*(.*)$/)
    if (m) {
      started = true
      if (m[2].trim()) {
        rows.push([m[1], m[2].trim()])
        contIdx = rows.length - 1
      } else {
        empty.push(m[1])
        contIdx = -1 // 빈 값 필드는 이어받지 않음
      }
    } else {
      // `key: value` 형식 밖 — 직전 값의 **다음 줄**(멀티라인 값, 스펙 255 개행 보존이 노출한 케이스).
      // 시작 전(문서 청크)이거나 이어붙일 필드가 없으면 엔티티 직렬화가 아니므로 원문 그대로(null).
      if (!started || contIdx < 0) return null
      rows[contIdx][1] += '\n' + raw.trim()
    }
  }
  // 필드 2개 미만이면 엔티티로 보기 어렵다(문서가 우연히 'word:'로 시작한 경우 방어 — 이전엔
  // 비형식 줄에서 즉시 null이라 자연 배제됐으나, 연속 줄 허용으로 헐거워진 만큼 개수로 조인다).
  if (rows.length + empty.length < 2) return null
  return rows.length ? { rows, empty } : null
}

export function EntityFields({ rows, empty, size = 13 }: { rows: [string, string][]; empty: string[]; size?: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {rows.map(([k, v]) => (
        <div key={k} style={{ fontSize: size, display: 'flex', gap: 8 }}>
          <span style={{ color: 'var(--color-text-tertiary)', minWidth: 118, flex: 'none', fontFamily: 'var(--font-family-code)', fontSize: size - 1 }}>{k}</span>
          <span style={{ color: 'var(--color-text-secondary)', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>{v}</span>
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
