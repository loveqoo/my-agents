/* Admin 콘솔 공유 UI 헬퍼 — 여러 뷰에서 재사용.
   handoff 번들 ui_kits/admin/adminShared.jsx를 진짜 antd 6/React+TS로 재현.
   토큰은 theme.css의 CSS 변수를 그대로 참조한다. */
import { type ReactNode, type CSSProperties, useRef, useState, useEffect } from 'react'
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

/* antd Grid 브레이크포인트(useBreakpoint 키와 동일). */
export type Breakpoint = 'xs' | 'sm' | 'md' | 'lg' | 'xl' | 'xxl'

export interface Column<T> {
  key: string
  title: ReactNode
  width?: number | string
  align?: 'left' | 'right' | 'center'
  render?: (row: T) => ReactNode
  /* 이 브레이크포인트 미만 폭에선 (데스크톱 표에서만) 숨긴다 — 가로 overflow 완화(스펙 095).
     모바일 카드 경로엔 적용 안 함(세로 배열이라 가로 공간 문제 없음). 상세는 row-click로. */
  hideBelow?: Breakpoint
  /* 오른쪽 고정(sticky). 미지정이라도 마지막 컬럼이 title 없으면(=액션) 자동 고정된다. */
  fixed?: 'right'
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
  const screens = Grid.useBreakpoint()
  // 데스크톱 표에서만 저우선 컬럼을 좁은 폭에서 숨겨 가로 overflow를 완화한다(스펙 095).
  // 훅은 모바일 early-return보다 앞에서 무조건 호출(순서 고정).
  const wrapRef = useRef<HTMLDivElement>(null)
  const [overflowing, setOverflowing] = useState(false)
  const visibleColumns = columns.filter((c) => !c.hideBelow || screens[c.hideBelow])
  const lastIdx = visibleColumns.length - 1
  // 마지막 컬럼이 title 없으면(=액션) 자동 오른쪽 고정. 명시 fixed:'right'도 존중.
  const isStickyRight = (c: Column<T>, i: number) => c.fixed === 'right' || (!c.title && i === lastIdx)
  // 래퍼가 실제로 가로로 넘칠 때만 sticky 셀에 왼쪽 그림자("더 있음")를 켠다.
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const check = () => setOverflowing(el.scrollWidth > el.clientWidth + 1)
    check()
    const ro = new ResizeObserver(check)
    ro.observe(el)
    return () => ro.disconnect()
  }, [visibleColumns.length, rows])

  // 모바일: 가로 스크롤 표 대신 행을 카드로 — 1열은 헤더, 나머지는 라벨:값, 빈 title(액션)은 라벨 없이.
  if (screens.md === false) {
    const [head, ...rest] = columns
    const labeled = rest.filter((c) => c.title)
    const actions = rest.filter((c) => !c.title)
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {rows.length === 0 ? (
          <Panel style={{ padding: '40px 16px', textAlign: 'center', color: 'var(--color-text-tertiary)' }}>
            {empty}
          </Panel>
        ) : (
          rows.map((r) => (
            <Panel key={String(cell(r, rowKey))} style={{ padding: 14 }}>
              <div
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                style={{ cursor: onRowClick ? 'pointer' : 'default' }}
              >
                {head && (
                  <div style={{ fontSize: 15, marginBottom: labeled.length ? 12 : 0 }}>
                    {head.render ? head.render(r) : (cell(r, head.key) as ReactNode)}
                  </div>
                )}
                {labeled.map((c) => (
                  <div
                    key={c.key}
                    style={{ display: 'flex', gap: 10, alignItems: 'baseline', padding: '4px 0', fontSize: 14 }}
                  >
                    <span style={{ minWidth: 80, flex: 'none', color: 'var(--color-text-tertiary)' }}>{c.title}</span>
                    <span style={{ flex: 1, minWidth: 0, display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', color: 'var(--color-text)' }}>
                      {c.render ? c.render(r) : (cell(r, c.key) as ReactNode)}
                    </span>
                  </div>
                ))}
                {actions.length > 0 && (
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 10 }}>
                    {actions.map((c) => (
                      <span key={c.key}>{c.render ? c.render(r) : (cell(r, c.key) as ReactNode)}</span>
                    ))}
                  </div>
                )}
              </div>
            </Panel>
          ))
        )}
      </div>
    )
  }

  // 오른쪽 고정 셀 공통 스타일 — 불투명 배경으로 스크롤된 셀이 비치지 않게, overflow일 때만 왼쪽 그림자.
  const stickyStyle = (bg: string): CSSProperties => ({
    position: 'sticky',
    right: 0,
    zIndex: 1,
    background: bg,
    boxShadow: overflowing ? 'inset 8px 0 8px -8px rgba(0,0,0,0.16)' : undefined,
  })
  return (
    <Panel>
      <div ref={wrapRef} style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14, minWidth: 'max-content' }}>
        <thead>
          <tr style={{ color: 'var(--color-text-secondary)', textAlign: 'left', background: 'var(--gray-2)' }}>
            {visibleColumns.map((c, i) => (
              <th
                key={c.key}
                style={{
                  padding: '11px 16px', fontWeight: 500, width: c.width, textAlign: c.align || 'left', whiteSpace: 'nowrap',
                  ...(isStickyRight(c, i) ? stickyStyle('var(--gray-2)') : null),
                }}
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
                colSpan={visibleColumns.length}
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
                  if (!onRowClick) return
                  e.currentTarget.style.background = 'var(--color-fill-quaternary)'
                  // sticky 셀은 불투명 배경이라 tr hover색이 안 비침 → 직접 hover색으로 맞춘다.
                  e.currentTarget.querySelectorAll<HTMLElement>('td[data-sticky]').forEach((td) => {
                    td.style.background = 'var(--color-fill-quaternary)'
                  })
                }}
                onMouseLeave={(e) => {
                  if (!onRowClick) return
                  e.currentTarget.style.background = 'transparent'
                  e.currentTarget.querySelectorAll<HTMLElement>('td[data-sticky]').forEach((td) => {
                    td.style.background = 'var(--color-bg-container)'
                  })
                }}
              >
                {visibleColumns.map((c, i) => (
                  <td
                    key={c.key}
                    data-sticky={isStickyRight(c, i) ? '' : undefined}
                    style={{
                      padding: '13px 16px', textAlign: c.align || 'left', color: 'var(--color-text)',
                      ...(isStickyRight(c, i) ? stickyStyle('var(--color-bg-container)') : null),
                    }}
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
  const screens = Grid.useBreakpoint()
  const isMobile = screens.md === false
  const bodyPad = isMobile ? 16 : 24
  // 래퍼 overflow:hidden — 닫힘 시 패널이 translateX(100%)로 화면 밖 오른쪽에 머물며
  // Content(overflow:auto)의 가로 스크롤을 만들던 문제 차단. 열림 시 패널은 경계 안.
  return (
    <div style={{ position: 'absolute', inset: 0, zIndex: 1000, overflow: 'hidden', pointerEvents: open ? 'auto' : 'none' }}>
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
          maxWidth: isMobile ? '100%' : '92%',
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
                padding: isMobile ? '14px 16px' : '16px 24px',
                borderBottom: '1px solid var(--color-border-secondary)',
                flex: 'none',
              }}
            >
              <span style={{ fontSize: 16, fontWeight: 600 }}>{title}</span>
              <span onClick={onClose} style={{ cursor: 'pointer', color: 'var(--color-text-tertiary)' }}>
                <CloseOutlined />
              </span>
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: bodyPad }}>{children}</div>
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

/* key/value 디스크립터 행. 모바일에선 라벨을 윗줄로 쌓아 값 영역을 넓힌다. */
export function Desc({ label, width = 120, children }: { label: ReactNode; width?: number; children?: ReactNode }) {
  const screens = Grid.useBreakpoint()
  const stack = screens.md === false
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: stack ? 'column' : 'row',
        alignItems: 'flex-start',
        gap: stack ? 4 : 0,
        padding: '10px 0',
        borderBottom: '1px solid var(--color-border-secondary)',
        fontSize: 14,
      }}
    >
      <div style={{ width: stack ? '100%' : width, color: 'var(--color-text-tertiary)', flex: 'none', paddingTop: 1 }}>{label}</div>
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
