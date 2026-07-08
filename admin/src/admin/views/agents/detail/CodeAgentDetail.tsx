/* 코드(SDK) 에이전트 상세 — 풀페이지(스펙 246 후속5). ui 상세와 **같은 뼈대**(DetailPageShell:
   좌측 탭 네비+개요 지도+활성 탭만 렌더) — 사용자 지적("소스별 상세 컴포넌트 차이가 크다") 반영.
   구성은 코드가 소유(읽기 전용), 배포는 코드 푸시로 생성. */
import { Tag, Button, Alert, Modal, Descriptions, Grid, Typography } from 'antd'
import { ExposeSwitch } from '../../../shared'
import { Icon } from '../../../icons'
import type { Agent } from '../../../mockData'
import { displayName } from '../../../naming'
import { PersonaStaleNote } from '../PersonaStaleNote'
import { DetailPageShell, SectionTitle, JumpCell, type DetailSection } from './DetailPageShell'

export function CodeAgentDetailPage({
  agent,
  onBack,
  onDelete,
  onClone,
  onResync,
  onToggleExpose,
  onSetVisibility,
  onRefreshPersona,
}: {
  agent: Agent
  onBack: () => void
  onDelete: (a: Agent) => void
  onClone: (a: Agent) => void
  onResync: (a: Agent) => void
  onToggleExpose: (a: Agent) => void
  onSetVisibility: (a: Agent, pub: boolean) => void
  onRefreshPersona: (a: Agent) => Promise<void>
}) {
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  const canManage = agent.can_manage !== false
  const kv = { column: 1 as const, size: 'small' as const, bordered: true, layout: (isMobile ? 'vertical' : 'horizontal') as 'vertical' | 'horizontal', labelStyle: { width: 120 } }

  const sections: DetailSection[] = [
    {
      key: 'overview',
      label: '개요',
      render: (jump) => (
        <section>
          <Descriptions
            {...kv}
            items={[
              {
                key: 'run',
                label: '실행',
                children: (
                  <span>
                    <span style={{ fontFamily: 'var(--font-family-code)' }}>{agent.model}</span>
                    <span style={{ color: 'var(--color-text-tertiary)' }}> · 페르소나 {agent.persona || '없음'} · 활성 세션 {agent.sessions ?? 0}개</span>
                  </span>
                ),
              },
              {
                key: 'config',
                label: '구성',
                children: (
                  <JumpCell onJump={() => jump('config')}>
                    {(() => {
                      const parts: string[] = []
                      if ((agent.mcps || []).length) parts.push(`도구 ${agent.mcps.length}`)
                      if ((agent.memories || []).length) parts.push(`메모리 ${agent.memories.length}`)
                      return parts.length ? `${parts.join(' · ')} (읽기 전용)` : '연결 없음 (읽기 전용)'
                    })()}
                  </JumpCell>
                ),
              },
              {
                key: 'deploy',
                label: '배포',
                children: (
                  <JumpCell onJump={() => jump('deploy')}>
                    서빙 {agent.commit || agent.activeVersion || '—'} · 마지막 동기화 {agent.lastSync || '—'}
                  </JumpCell>
                ),
              },
              {
                key: 'sharing',
                label: '공개·연동',
                children: (
                  <JumpCell onJump={() => jump('sharing')}>
                    {agent.owner_id == null ? 'public(모두 사용 가능)' : 'private(소유자만)'} · A2A {agent.exposed?.a2a ? '켬(중계)' : '꺼짐'}
                  </JumpCell>
                ),
              },
            ]}
          />
          <Alert
            style={{ marginTop: 12 }}
            type="info"
            showIcon
            title="SDK로 코드 정의해 원격 엔드포인트에서 실행되는 에이전트입니다. 구성은 코드가 소유하므로 콘솔에서는 읽기 전용입니다 — 변경하려면 코드를 수정해 다시 배포한 뒤 동기화하세요."
          />
          <PersonaStaleNote agent={agent} onRefresh={onRefreshPersona} />
        </section>
      ),
    },
    {
      key: 'config',
      label: '구성',
      render: () => (
        <section>
          <Descriptions
            {...kv}
            items={[
              { key: 'model', label: '모델', children: <span style={{ fontFamily: 'var(--font-family-code)' }}>{agent.model}</span> },
              { key: 'persona', label: '페르소나', children: agent.persona || '없음' },
              {
                key: 'history',
                label: '채팅 히스토리',
                children: agent.historyDepth ? `최근 ${agent.historyDepth}개 메시지` : '기억 안 함',
              },
              ...((agent.memories || []).length
                ? [{
                    key: 'memories',
                    label: '메모리',
                    children: (
                      <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                        {agent.memories.map((m) => <Tag key={m} color="purple">{m}</Tag>)}
                      </span>
                    ),
                  }]
                : []),
              ...((agent.mcps || []).length
                ? [{
                    key: 'mcps',
                    label: 'MCP',
                    children: (
                      <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                        {agent.mcps.map((m) => <Tag key={m} color="cyan">{m}</Tag>)}
                      </span>
                    ),
                  }]
                : []),
              { key: 'sessions', label: '세션', children: <>활성 {agent.sessions ?? 0}개</> },
            ]}
          />
          {(() => {
            const empty: string[] = []
            if (!(agent.memories || []).length) empty.push('메모리')
            if (!(agent.mcps || []).length) empty.push('도구(MCP)')
            return empty.length ? (
              <div style={{ fontSize: 12, color: 'var(--color-text-quaternary)', marginTop: 8 }}>
                연결 없음: {empty.join(' · ')}
              </div>
            ) : null
          })()}
        </section>
      ),
    },
    {
      key: 'deploy',
      label: '배포·연결',
      render: () => (
        <section>
          <Descriptions
            {...kv}
            items={[
              {
                key: 'endpoint',
                label: 'Endpoint',
                children: agent.endpoint ? (
                  <Typography.Text code copyable={{ text: agent.endpoint, tooltips: ['복사', '복사됨'] }} ellipsis style={{ fontFamily: 'var(--font-family-code)', fontSize: 12, maxWidth: '100%' }}>
                    {agent.endpoint}
                  </Typography.Text>
                ) : '—',
              },
              {
                key: 'token',
                label: 'Access token',
                children: (
                  <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 12 }}>{agent.token || '—'}</code>
                    <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>마스킹 표시 · 콘솔에 평문 저장 안 함</span>
                  </span>
                ),
              },
              { key: 'runtime', label: '런타임', children: <span style={{ fontFamily: 'var(--font-family-code)', fontSize: 13 }}>{agent.runtime || '—'}</span> },
              {
                key: 'source',
                label: '소스',
                children: (
                  <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13 }}>
                    {agent.repo}
                    {agent.commit ? '@' + agent.commit : ''}
                  </code>
                ),
              },
              { key: 'registered', label: '등록일', children: agent.registeredAt || '—' },
              {
                key: 'sync',
                label: '동기화',
                children: (
                  <span style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <span style={{ flex: 1, minWidth: 160, fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                      마지막 동기화 · {agent.lastSync || '—'}
                    </span>
                    <Button size="small" icon={<Icon name="sync" />} onClick={() => onResync(agent)}>
                      재동기화
                    </Button>
                  </span>
                ),
              },
            ]}
          />
          <div style={{ marginTop: 16 }}>
            <SectionTitle>배포 히스토리</SectionTitle>
            <div style={{ border: '1px solid var(--color-border-secondary)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
              {(agent.versions || []).map((v, i) => (
                <div
                  key={v.version}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
                    borderTop: i ? '1px solid var(--color-border-secondary)' : 'none',
                    background: v.status === 'active' ? 'var(--color-success-bg)' : 'transparent',
                  }}
                >
                  <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', width: 64 }}>
                    {v.version}
                  </code>
                  {v.status === 'active' ? <Tag color="green">서빙 중</Tag> : <Tag>이전 배포</Tag>}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, color: 'var(--color-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {v.note}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>{v.createdAt}</div>
                  </div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
              배포는 코드 푸시로 생성됩니다 — 콘솔에서 새 버전을 만들거나 활성화하지 않습니다.
            </div>
          </div>
        </section>
      ),
    },
    {
      key: 'sharing',
      label: '공개·연동',
      render: () => (
        <section>
          <Descriptions
            {...kv}
            items={[
              {
                key: 'visibility',
                label: '공개 범위',
                children: (
                  <span style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <span style={{ flex: 1, minWidth: 180 }}>
                      {agent.owner_id == null ? 'public · 모두 사용 가능(A2A 켜기 가능)' : 'private · 소유자만 사용(A2A 불가)'}
                    </span>
                    {canManage && (
                      <Button
                        size="small"
                        onClick={() =>
                          Modal.confirm({
                            title: agent.owner_id == null ? '비공개(private)로 전환할까요?' : '공개(public)로 전환할까요?',
                            content:
                              agent.owner_id == null
                                ? 'private가 되면 소유자만 사용할 수 있고, 켜져 있던 A2A 공개는 자동으로 꺼집니다.'
                                : 'public이 되면 모든 사용자가 사용할 수 있고 A2A 공개(서버가 1홉 중계)도 켤 수 있습니다.',
                            okText: '전환',
                            cancelText: '취소',
                            onOk: () => onSetVisibility(agent, agent.owner_id != null),
                          })
                        }
                      >
                        {agent.owner_id == null ? '비공개로 전환' : '공개로 전환'}
                      </Button>
                    )}
                  </span>
                ),
              },
              {
                key: 'a2a',
                label: 'A2A 공개',
                children: (
                  <ExposeSwitch
                    on={!!agent.exposed.a2a}
                    onChange={() => onToggleExpose(agent)}
                    label=""
                    onText="켬 · 우리 A2A 주소로 호출을 중계"
                    offText="꺼짐 · 노출되지 않음"
                  />
                ),
              },
            ]}
          />
        </section>
      ),
    },
  ]

  return (
    <DetailPageShell
      onBack={onBack}
      avatar={<Icon name="code" />}
      name={displayName(agent)}
      agentId={agent.agentId}
      badges={
        <>
          <Tag color="geekblue" style={{ margin: 0 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <Icon name="code" size={11} /> Code
            </span>
          </Tag>
          <Tag color="green" style={{ margin: 0 }}>
            서빙 <code style={{ fontFamily: 'var(--font-family-code)' }}>{agent.commit || agent.activeVersion}</code>
          </Tag>
          <Tag style={{ margin: 0 }}>{agent.owner_id == null ? 'public' : 'private'}</Tag>
          {agent.exposed?.a2a && <Tag color="green" style={{ margin: 0 }}>A2A</Tag>}
        </>
      }
      actions={
        <>
          <Button icon={<Icon name="copy" />} onClick={() => onClone(agent)}>
            복제
          </Button>
          {canManage ? (
            <Button danger icon={<Icon name="delete" />} onClick={() => onDelete(agent)}>
              등록 해제
            </Button>
          ) : (
            <span style={{ color: 'var(--color-text-tertiary)', alignSelf: 'center' }}>다른 사용자 소유 — 관리 권한 없음</span>
          )}
        </>
      }
      sections={sections}
    />
  )
}
