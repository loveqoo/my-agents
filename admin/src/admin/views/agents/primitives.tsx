import { Icon } from '../../icons'

export function Field({ label, children }: { label: React.ReactNode; children?: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontSize: 14, color: 'var(--color-text)', fontWeight: 500 }}>{label}</span>
      {children}
    </label>
  )
}

/* 폼 3단계 구획 머리말(스펙 109) — 기본 / 이 에이전트가 하는 일 / (세부 설정은 Collapse 자체 라벨).
   first=첫 구획(맨 위)은 상단 구분선 없음. */
export function SectionHeader({ children, first }: { children: React.ReactNode; first?: boolean }) {
  return (
    <div
      style={{
        fontSize: 12,
        fontWeight: 600,
        color: 'var(--color-text-tertiary)',
        letterSpacing: 0.3,
        marginTop: first ? 0 : 4,
        paddingTop: first ? 0 : 8,
        borderTop: first ? 'none' : '1px solid var(--color-border-secondary)',
      }}
    >
      {children}
    </div>
  )
}

/* ---- Detail drawer ---- */
export function IdRow({ label, value }: { label: React.ReactNode; value: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
      <span style={{ width: 84, flex: 'none', fontSize: 12, color: 'var(--color-text-tertiary)' }}>{label}</span>
      <code
        style={{
          flex: 1,
          minWidth: 0,
          fontFamily: 'var(--font-family-code)',
          fontSize: 12,
          color: 'var(--color-text)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {value}
      </code>
      <span
        onClick={() => navigator.clipboard && navigator.clipboard.writeText(value)}
        title="Copy"
        style={{ cursor: 'pointer', color: 'var(--color-text-tertiary)', display: 'inline-flex', flex: 'none' }}
      >
        <Icon name="copy" size={13} />
      </span>
    </div>
  )
}
