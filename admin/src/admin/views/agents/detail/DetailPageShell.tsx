/* 상세 페이지 공용 셸(스펙 246 후속5 — 사용자 지적 "소스별 상세 컴포넌트 차이가 크다").
   상단 문법(돌아가기·정체성 바·1층 배지·액션)뿐 아니라 **2층 탭 구조까지 셸이 소유** —
   ui/code/external 셋이 같은 뼈대(좌측 네비+활성 탭만 렌더+개요 지도)를 쓴다.
   내용이 적어도 탭 구조는 유지(구조 일관성 > 밀도 최적화 — 사용자 결정). */
import { useState } from 'react'
import { Avatar, Button, Tooltip, message, Grid } from 'antd'
import { Icon } from '../../../icons'

export interface DetailSection {
  key: string
  label: string
  // 활성 탭만 마운트. jump로 다른 탭 이동(개요 지도의 점프에 사용).
  render: (jump: (key: string) => void) => React.ReactNode
}

export function DetailPageShell({
  onBack,
  avatar,
  name,
  agentId,
  badges,
  actions,
  sections,
  aboveTabs,
}: {
  onBack: () => void
  avatar: React.ReactNode
  name: React.ReactNode
  agentId: string
  badges: React.ReactNode
  actions: React.ReactNode
  sections: DetailSection[]
  aboveTabs?: React.ReactNode // 탭 위 공통 알림(설정 실패 등)
}) {
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  const [active, setActive] = useState(sections[0]?.key ?? '')
  const jump = (key: string) => setActive(key)
  const current = sections.find((s) => s.key === active) ?? sections[0]

  return (
    <div style={{ maxWidth: 1040, margin: '0 auto', width: '100%' }}>
      <div style={{ marginBottom: 10 }}>
        <Button
          type="text"
          size="small"
          icon={<Icon name="arrow-left" size={12} />}
          onClick={onBack}
          style={{ color: 'var(--color-text-tertiary)', paddingInline: 4 }}
        >
          에이전트 목록
        </Button>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <Avatar size="large" style={{ background: 'var(--gray-12)' }}>
          {avatar}
        </Avatar>
        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 16, fontWeight: 600 }}>{name}</span>
            <Tooltip title={<span style={{ fontFamily: 'var(--font-family-code)' }}>{agentId}</span>}>
              <Button
                type="text"
                size="small"
                icon={<Icon name="copy" size={12} />}
                onClick={() => {
                  void navigator.clipboard.writeText(agentId)
                  message.success('Agent ID 복사됨')
                }}
              />
            </Tooltip>
          </div>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 2 }}>{badges}</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>{actions}</div>
      </div>

      {aboveTabs}

      <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: 24 }}>
        <div
          style={
            isMobile
              ? { display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 8 }
              : { display: 'flex', flexDirection: 'column', gap: 2, position: 'sticky', top: 12, minWidth: 120 }
          }
        >
          {sections.map((s) => (
            <Button
              key={s.key}
              type={active === s.key ? 'primary' : 'text'}
              size="small"
              style={{ justifyContent: 'flex-start', flexShrink: 0 }}
              onClick={() => jump(s.key)}
            >
              {s.label}
            </Button>
          ))}
        </div>
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 24 }}>
          {current?.render(jump)}
        </div>
      </div>
    </div>
  )
}

/* 공용 섹션 제목 — 셋(ui/code/external)이 같은 시각 언어. */
export function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', marginBottom: 10, paddingBottom: 6, borderBottom: '1px solid var(--color-border-secondary)' }}>
      {children}
    </div>
  )
}

/* 개요 지도용 값 셀 점프 래퍼 — 값 셀 전체 클릭 + 우측 화살표(셋 공용). */
export function JumpCell({ onJump, children }: { onJump: () => void; children: React.ReactNode }) {
  return (
    <span
      onClick={onJump}
      style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', width: '100%' }}
    >
      <span style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{children}</span>
      <Icon name="right" size={11} style={{ color: 'var(--color-text-quaternary)', flexShrink: 0 }} />
    </span>
  )
}
