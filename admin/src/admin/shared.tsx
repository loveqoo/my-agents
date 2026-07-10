/* Admin 콘솔 공유 UI 헬퍼 — 여러 뷰에서 재사용.
   handoff 번들 ui_kits/admin/adminShared.jsx를 진짜 antd 6/React+TS로 재현.
   토큰은 theme.css의 CSS 변수를 그대로 참조한다. */
import { type ReactNode, type CSSProperties } from 'react'
import { Tag, Button, Switch, Grid, Badge, Card as AntCard, Drawer as AntDrawer, Table as AntTable, type TableColumnsType } from 'antd'
import { Icon } from './icons'
import { VERSION_STATUS, type VersionMeta } from './mockData'

/* 제목+액션 툴바가 달린 페이지 패딩 래퍼. */
export function Page({
  subtitle,
  actions,
  children,
}: {
  // 스펙 213: 제목은 **상단 헤더(AdminShell TITLES[view])가 단독 표시** — Page는 렌더하지 않는다
  // (메뉴 라벨과 중복 제거). 호출부 호환을 위해 prop은 받되 무시한다(점진 정리는 별도).
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
      {(subtitle || actions) && (
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
            {subtitle && (
              <div style={{ color: 'var(--color-text-tertiary)', fontSize: 14 }}>
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
  // antd Badge(색점+텍스트)로 통일(스펙 204) — 호출부 시그니처 불변.
  return <Badge color={color} text={<span style={{ fontSize: 14, color: 'var(--color-text)' }}>{label}</span>} />
}

/* 소유 표시 태그(스펙 114) — owner_id·can_manage로 파생. 백엔드가 판정을 소유하므로(learning 113)
   프론트는 재계산 없이 표시만: null=공유, 관리 불가=다른 사용자, 관리 가능+소유=null(태그 없음). */
export function OwnerTag({ ownerId, canManage, meId }: { ownerId?: string | null; canManage?: boolean; meId?: string }) {
  // 최소 어휘(스펙 147): public/private/private·타인. '타인' 판정은 meId 비교 우선 —
  // can_manage는 admin에게 항상 true라 admin 시야에서 타인 구분이 사라진다(e2e 147 실측).
  if (ownerId == null) return <Tag>public</Tag>
  const others = meId !== undefined ? ownerId !== meId : canManage === false
  if (others) return <Tag color="orange">private · 타인</Tag>
  return <Tag color="blue">private</Tag>
}

/* 테두리가 있는 카드 표면(테이블 패널 등) — antd Card로 통일(스펙 204). body 패딩 0 = 구 Panel과
   동일 시맨틱(내용물이 표 등 자체 패딩 보유), overflow hidden은 루트 스타일로 보존. */
export function Panel({ children, style }: { children?: ReactNode; style?: CSSProperties }) {
  return (
    <AntCard style={{ overflow: 'hidden', ...style }} styles={{ body: { padding: 0 } }}>
      {children}
    </AntCard>
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
  subRow,
  rowTint,
}: {
  columns: Column<T>[]
  rows: T[]
  onRowClick?: (row: T) => void
  rowKey?: string
  empty?: ReactNode
  /* 행 강조(스펙 284 — 내 것 tint). 데탑=본행+보조행(tr 클래스), 모바일=카드 배경. */
  rowTint?: (row: T) => boolean
  /* 행당 보조 줄(스펙 146) — 메타 태그처럼 컬럼 격자에 안 맞는 내용을 두 번째 줄에 폭 전체로.
     마지막 액션 컬럼은 rowSpan=2로 두 줄에 걸친다. 모바일 카드에선 하단 섹션으로 합류. */
  subRow?: (row: T) => ReactNode
}) {
  const cell = (r: T, k: string) => (r as Record<string, unknown>)[k]
  const screens = Grid.useBreakpoint()
  // 저우선 컬럼은 좁은 폭에서 숨겨 가로 overflow 완화(스펙 095) — antd responsive 대신 기존
  // hideBelow 시맨틱을 여기서 그대로 적용(호출부 무변경).
  const visibleColumns = columns.filter((c) => !c.hideBelow || screens[c.hideBelow])

  // 모바일: 가로 스크롤 표 대신 행을 카드로 — 1열은 헤더, 나머지는 라벨:값, 빈 title(액션)은 라벨 없이.
  // 카드 스택 전환점 lg(992) — 컬럼 많은 표는 768~992 태블릿 구간에서도 비좁다(스펙 145 실측:
  // 에이전트 표 intrinsic 890px). "숨기지도 밀지도 않는다" 원칙상 이 구간은 카드가 정답.
  if (screens.lg === false) {
    const [head, ...rest] = columns
    const labeled = rest.filter((c) => c.title)
    const actions = rest.filter((c) => !c.title)
    // 카드 스택 = flex 레이아웃 + Panel(=antd Card). antd List는 v6에서 deprecated(제거 예정)이라
    // 목록이어도 List로 옮기지 않는다 — Flex 프리미티브 위 Card 조립이 규칙 부합이자 미래지향(스펙 207).
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {rows.length === 0 ? (
          <Panel style={{ padding: '40px 16px', textAlign: 'center', color: 'var(--color-text-tertiary)' }}>
            {empty}
          </Panel>
        ) : (
          rows.map((r) => (
            <Panel key={String(cell(r, rowKey))} style={{ padding: 14, ...(rowTint?.(r) ? { background: 'rgba(82,196,26,0.09)' } : {}) }}>
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
                {subRow ? (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>{subRow(r)}</div>
                ) : null}
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

  // 데스크톱: antd Table 채택(스펙 187 Phase 2) — hover·헤더 스타일·a11y·빈 상태를 antd가 제공,
  // 커스텀 sticky·ResizeObserver 재구현 제거. prop API는 그대로(호출부 무변경).
  // subRow(스펙 146)는 expandable로 매핑: 전 행 강제 확장 + 확장 컬럼 숨김 = 상시 2줄 행.
  // theme.css의 .dt-antd-sub 규칙이 본행-보조행 경계를 지워 "두 줄이 한 몸" 룩을 보존한다.
  type Row = Record<string, unknown>
  const data = rows as unknown as Row[]
  const antdColumns: TableColumnsType<Row> = visibleColumns.map((c) => ({
    key: c.key,
    title: c.title,
    dataIndex: c.key,
    width: c.width,
    align: c.align,
    render: c.render ? (_: unknown, r: Row) => c.render!(r as unknown as T) : undefined,
  }))
  return (
    <Panel>
      <AntTable<Row>
        className={subRow ? 'dt-antd dt-antd-sub' : 'dt-antd'}
        dataSource={data}
        columns={antdColumns}
        rowKey={(r) => String(r[rowKey])}
        pagination={false}
        tableLayout="fixed"
        locale={{ emptyText: empty }}
        rowClassName={(r) => (rowTint?.(r as unknown as T) ? 'dt-row-tint' : '')}
        onRow={(r) => ({
          onClick: onRowClick ? () => onRowClick(r as unknown as T) : undefined,
          style: onRowClick ? { cursor: 'pointer' } : undefined,
        })}
        expandable={
          subRow
            ? {
                expandedRowRender: (r) => (
                  <div
                    onClick={onRowClick ? () => onRowClick(r as unknown as T) : undefined}
                    style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', cursor: onRowClick ? 'pointer' : 'default' }}
                  >
                    {subRow(r as unknown as T)}
                  </div>
                ),
                // defaultExpandAllRows는 최초 렌더만 반영 — 생성으로 추가된 행도 펼치려면 controlled.
                expandedRowKeys: data.map((r) => String(r[rowKey])),
                expandedRowClassName: (r: Row) => (rowTint?.(r as unknown as T) ? 'dt-row-tint' : ''),
                showExpandColumn: false,
              }
            : undefined
        }
      />
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
  // antd Drawer 채택(스펙 187) — 포커스 트랩·Escape(keyboard)·스크롤락·마스크·슬라이드 애니메이션을
  // antd가 제공하므로 커스텀 95줄 재구현을 제거. prop API는 그대로 유지(호출부 무변경). 모바일 100% 폭·
  // footer 우측 정렬만 보존. destroyOnHidden=닫힘 시 body 언마운트(구 `{open && ...}` 시맨틱 동치).
  return (
    <AntDrawer
      open={open}
      title={title}
      size={isMobile ? '100%' : width}
      onClose={onClose}
      destroyOnHidden
      footer={
        footer ? (
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>{footer}</div>
        ) : undefined
      }
    >
      {children}
    </AntDrawer>
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
  ops,
}: {
  versions?: VersionMeta[]
  onActivate?: (v: VersionMeta) => void
  onTest?: (v: VersionMeta) => void
  onNewDraft?: (() => void) | null
  onRevert?: (v: VersionMeta) => void
  // 버전 운영 지표(스펙 244, 옵셔널 — 미전달 소비자 무회귀): version → {evalRuns,lastScore,autoRuns,up,down}
  ops?: Record<string, { evalRuns: number; lastScore: number | null; autoRuns: number; errorRuns?: number; up: number; down: number }>
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
      {/* 테두리 컨테이너 + Flex 행 스택(List v6 deprecated → Flex 조립, 스펙 208). 상태별 배경·행 구성
          보존, 항목 간 구분선은 첫 행 제외 borderTop(bordered List 디바이더 동치). */}
      <div style={{ border: '1px solid var(--color-border)', borderRadius: 8, overflow: 'hidden' }}>
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
                borderTop: i > 0 ? '1px solid var(--color-border)' : undefined,
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
                {/* 운영 칩(스펙 244) — 이 버전의 성적·피드백. 데이터 없으면 무소음. */}
                {(() => {
                  const o = ops?.[v.version]
                  if (!o || (o.evalRuns === 0 && o.up === 0 && o.down === 0)) return null
                  return (
                    <div style={{ display: 'flex', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                      {o.evalRuns > 0 && (
                        <Tag color={o.lastScore != null && o.lastScore >= 0.8 ? 'green' : o.lastScore != null ? 'orange' : 'default'} style={{ margin: 0, fontSize: 11 }}>
                          평가 {o.lastScore != null ? Math.round(o.lastScore * 100) + '% (최근 성공)' : '—'} · {o.evalRuns}회
                        </Tag>
                      )}
                      {o.autoRuns > 0 && <Tag color="purple" style={{ margin: 0, fontSize: 11 }}>자동회귀 {o.autoRuns}</Tag>}
                      {(o.errorRuns ?? 0) > 0 && <Tag color="red" style={{ margin: 0, fontSize: 11 }}>실패 {o.errorRuns}</Tag>}
                      {(o.up > 0 || o.down > 0) && (
                        <Tag style={{ margin: 0, fontSize: 11 }}>👍{o.up} 👎{o.down}</Tag>
                      )}
                    </div>
                  )
                })()}
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

