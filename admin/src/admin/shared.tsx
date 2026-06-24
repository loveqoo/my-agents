/* Admin 콘솔 공유 UI 헬퍼 — 여러 뷰에서 재사용.
   handoff 번들 ui_kits/admin/adminShared.jsx를 진짜 antd 6/React+TS로 재현.
   토큰은 theme.css의 CSS 변수를 그대로 참조한다. */
import { type ReactNode, type CSSProperties } from 'react'
import { Tag, Button, Switch, Grid } from 'antd'
import { CloseOutlined } from '@ant-design/icons'
import { Icon } from './icons'
import { VERSION_STATUS, type VersionMeta } from './mockData'

/* 제목+액션 툴바가 달린 페이지 패딩 래퍼. */
export function Page({
  title,
  subtitle,
  actions,
  children,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children?: ReactNode
}) {
  const screens = Grid.useBreakpoint()
  const pad = screens.md ? 24 : 16
  // 모바일에서는 제목과 액션을 세로로 쌓는다 — 한 줄에 두면 제목이 버튼에 밀려 깨진다.
  return (
    <div style={{ padding: pad, maxWidth: 1200, margin: '0 auto', width: '100%' }}>
      {(title || actions) && (
        <div
          style={{
            display: 'flex',
            flexDirection: screens.md ? 'row' : 'column',
            alignItems: screens.md ? 'flex-end' : 'stretch',
            gap: screens.md ? 16 : 12,
            marginBottom: 20,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            {title && <h3 style={{ fontSize: 20, margin: 0 }}>{title}</h3>}
            {subtitle && (
              <div style={{ color: 'var(--color-text-tertiary)', marginTop: 4, fontSize: 14 }}>
                {subtitle}
              </div>
            )}
          </div>
          {actions}
        </div>
      )}
      {children}
    </div>
  )
}

/* 상태 알약: 색 점 + 라벨. */
export function StatusPill({ color, label }: { color: string; label: ReactNode }) {
  return (
    <span
      style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 14, color: 'var(--color-text)' }}
    >
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: color, flex: 'none' }} />
      {label}
    </span>
  )
}

/* 테두리가 있는 카드 표면(테이블 패널 등). */
export function Panel({ children, style }: { children?: ReactNode; style?: CSSProperties }) {
  return (
    <div
      style={{
        background: 'var(--color-bg-container)',
        border: '1px solid var(--color-border-secondary)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

export interface Column<T> {
  key: string
  title: ReactNode
  width?: number | string
  align?: 'left' | 'right' | 'center'
  render?: (row: T) => ReactNode
}

/* 단순 테이블. antd Table 대신 디자인 명세에 맞춘 경량 표.
   T는 제약 없이 받고 키 접근은 내부에서 캐스팅 — 인터페이스 타입도 그대로 넘길 수 있다. */
export function DataTable<T>({
  columns,
  rows,
  onRowClick,
  rowKey = 'id',
  empty = '데이터 없음',
}: {
  columns: Column<T>[]
  rows: T[]
  onRowClick?: (row: T) => void
  rowKey?: string
  empty?: ReactNode
}) {
  const cell = (r: T, k: string) => (r as Record<string, unknown>)[k]
  return (
    <Panel>
      {/* 좁은 화면에서는 표를 가로 스크롤 — 셀이 잘리거나 짜부라지지 않게. */}
      <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14, minWidth: 'max-content' }}>
        <thead>
          <tr style={{ color: 'var(--color-text-secondary)', textAlign: 'left', background: 'var(--gray-2)' }}>
            {columns.map((c) => (
              <th
                key={c.key}
                style={{ padding: '11px 16px', fontWeight: 500, width: c.width, textAlign: c.align || 'left', whiteSpace: 'nowrap' }}
              >
                {c.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                style={{ padding: '40px 16px', textAlign: 'center', color: 'var(--color-text-tertiary)' }}
              >
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <tr
                key={String(cell(r, rowKey))}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                style={{ borderTop: '1px solid var(--color-border-secondary)', cursor: onRowClick ? 'pointer' : 'default' }}
                onMouseEnter={(e) => {
                  if (onRowClick) e.currentTarget.style.background = 'var(--color-fill-quaternary)'
                }}
                onMouseLeave={(e) => {
                  if (onRowClick) e.currentTarget.style.background = 'transparent'
                }}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    style={{ padding: '13px 16px', textAlign: c.align || 'left', color: 'var(--color-text)' }}
                  >
                    {c.render ? c.render(r) : (cell(r, c.key) as ReactNode)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
      </div>
    </Panel>
  )
}

/* 오른쪽 슬라이드오버 드로어. AdminShell이 position:relative라 absolute로 덮는다. */
export function Drawer({
  open,
  title,
  width = 480,
  onClose,
  footer,
  children,
}: {
  open: boolean
  title?: ReactNode
  width?: number
  onClose?: () => void
  footer?: ReactNode
  children?: ReactNode
}) {
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 1000, pointerEvents: open ? 'auto' : 'none' }}>
      <div
        onClick={onClose}
        style={{ position: 'absolute', inset: 0, background: 'var(--color-bg-mask)', opacity: open ? 1 : 0, transition: 'opacity .25s' }}
      />
      <div
        style={{
          position: 'absolute',
          top: 0,
          right: 0,
          bottom: 0,
          width,
          maxWidth: '92%',
          background: '#fff',
          boxShadow: 'var(--box-shadow)',
          display: 'flex',
          flexDirection: 'column',
          transform: open ? 'translateX(0)' : 'translateX(100%)',
          transition: 'transform .25s cubic-bezier(.08,.82,.17,1)',
        }}
      >
        {open && (
          <>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '16px 24px',
                borderBottom: '1px solid var(--color-border-secondary)',
                flex: 'none',
              }}
            >
              <span style={{ fontSize: 16, fontWeight: 600 }}>{title}</span>
              <span onClick={onClose} style={{ cursor: 'pointer', color: 'var(--color-text-tertiary)' }}>
                <CloseOutlined />
              </span>
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>{children}</div>
            {footer && (
              <div
                style={{
                  flex: 'none',
                  display: 'flex',
                  justifyContent: 'flex-end',
                  gap: 8,
                  padding: 16,
                  borderTop: '1px solid var(--color-border-secondary)',
                }}
              >
                {footer}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

/* key/value 디스크립터 행. */
export function Desc({ label, width = 120, children }: { label: ReactNode; width?: number; children?: ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        padding: '10px 0',
        borderBottom: '1px solid var(--color-border-secondary)',
        fontSize: 14,
      }}
    >
      <div style={{ width, color: 'var(--color-text-tertiary)', flex: 'none', paddingTop: 1 }}>{label}</div>
      <div
        style={{ color: 'var(--color-text)', flex: 1, minWidth: 0, display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}
      >
        {children}
      </div>
    </div>
  )
}

/* 버전 이력 목록 + 라이프사이클 액션. 에이전트(·MCP 서버)에서 공유.
   onActivate(v): 초안/보관 버전을 활성으로 승격, onTest(v): 초안 테스트,
   onNewDraft(): 새 초안 포크, onRevert(v): 초안으로 되돌리기. */
export function VersionHistory({
  versions = [],
  onActivate,
  onTest,
  onNewDraft,
  onRevert,
}: {
  versions?: VersionMeta[]
  onActivate?: (v: VersionMeta) => void
  onTest?: (v: VersionMeta) => void
  onNewDraft?: (() => void) | null
  onRevert?: (v: VersionMeta) => void
}) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', flex: 1 }}>버전</span>
        {onNewDraft && (
          <Button type="dashed" size="small" icon={<Icon name="plus" />} onClick={onNewDraft}>
            새 초안
          </Button>
        )}
      </div>
      <div style={{ border: '1px solid var(--color-border-secondary)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
        {versions.map((v, i) => {
          const st = VERSION_STATUS[v.status] || VERSION_STATUS.archived
          return (
            <div
              key={v.version}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 14px',
                borderTop: i ? '1px solid var(--color-border-secondary)' : 'none',
                background:
                  v.status === 'active' ? 'var(--color-success-bg)' : v.status === 'draft' ? 'var(--gold-1)' : 'transparent',
              }}
            >
              <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', width: 34 }}>
                {v.version}
              </code>
              <Tag color={st.tag === 'default' ? undefined : st.tag}>{st.label}</Tag>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: 'var(--color-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {v.note}
                </div>
                <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>{v.createdAt}</div>
              </div>
              {v.status === 'draft' && onTest && (
                <Button type="primary" size="small" icon={<Icon name="thunderbolt" />} onClick={() => onTest(v)}>
                  테스트
                </Button>
              )}
              {v.status !== 'active' && onActivate && (
                <Button size="small" icon={<Icon name="check" />} onClick={() => onActivate(v)}>
                  활성화
                </Button>
              )}
              {v.status !== 'draft' && onRevert && (
                <Button type="text" size="small" icon={<Icon name="redo" />} onClick={() => onRevert(v)} title="초안으로 되돌리기" />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* 공개 on/off 스위치 + 라벨. */
export function ExposeSwitch({
  on,
  onChange,
  label,
  onText = '공개',
  offText = '비공개',
}: {
  on: boolean
  onChange?: (checked: boolean) => void
  label: ReactNode
  onText?: ReactNode
  offText?: ReactNode
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '12px 14px',
        border: '1px solid var(--color-border-secondary)',
        borderRadius: 'var(--radius-lg)',
        background: 'var(--gray-2)',
      }}
    >
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-text-heading)' }}>{label}</div>
        <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{on ? onText : offText}</div>
      </div>
      <Switch checked={on} onChange={onChange} />
    </div>
  )
}

/* mock 뷰 상단에 붙이는 "데모 데이터" 표기 배너. */
export function DemoBanner({ note }: { note?: ReactNode }) {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        fontSize: 12,
        color: 'var(--color-warning)',
        background: 'var(--color-warning-bg)',
        border: '1px solid var(--color-warning)',
        borderRadius: 100,
        padding: '2px 12px',
        marginBottom: 16,
      }}
    >
      ● 데모 데이터 {note}
    </div>
  )
}
