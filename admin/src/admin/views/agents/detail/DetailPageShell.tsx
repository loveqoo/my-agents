/* 상세 페이지 공용 셸(스펙 246 후속 — 소스별 상세의 문법 통일). 중앙 컨테이너(1040px)+
   돌아가기 줄+정체성 바(아바타·이름·복사 강등·1층 배지·액션). 본문은 소스별 컴포넌트가 소유.
   2층 탭은 관심사가 많을 때(ui 에이전트)의 장치 — 내용 적은 code/external은 단일 컬럼. */
import { Avatar, Button, Tooltip, message } from 'antd'
import { Icon } from '../../../icons'

export function DetailPageShell({
  onBack,
  avatar,
  name,
  agentId,
  badges,
  actions,
  children,
}: {
  onBack: () => void
  avatar: React.ReactNode
  name: React.ReactNode
  agentId: string
  badges: React.ReactNode
  actions: React.ReactNode
  children: React.ReactNode
}) {
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
      {children}
    </div>
  )
}
