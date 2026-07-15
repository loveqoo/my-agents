/* 코드(SDK) 에이전트 상세 — 풀페이지(스펙 246 후속5). ui 상세와 **같은 뼈대**(DetailPageShell:
   좌측 탭 네비+개요 지도+활성 탭만 렌더) — 사용자 지적("소스별 상세 컴포넌트 차이가 크다") 반영.
   구성은 코드가 소유(읽기 전용), 배포는 코드 푸시로 생성. */
import { Tag, Button, Alert, Modal, Descriptions, Grid, Typography, Tooltip } from 'antd'
import { ExposeSwitch } from '../../../shared'
import { Icon } from '../../../icons'
import { type Agent } from '../../../mockData'
import { displayName } from '../../../naming'
import { DetailPageShell, SectionTitle, JumpCell, type DetailSection } from './DetailPageShell'

export function CodeAgentDetailPage({
  agent,
  onBack,
  onDelete,
  onClone,
  onResync,
  onToggleExpose,
  onSetVisibility,
}: {
  agent: Agent
  onBack: () => void
  onDelete: (a: Agent) => void
  onClone: (a: Agent) => void
  onResync: (a: Agent) => void
  onToggleExpose: (a: Agent) => void
  onSetVisibility: (a: Agent, pub: boolean) => void
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
                  // 모델·활성 세션만(스펙 286 후속 — ui 상세와 같은 문법, 프롬프트는 구성 탭이 소유).
                  <span>
                    <span style={{ fontFamily: 'var(--font-family-code)' }}>{agent.model}</span>
                    <span style={{ color: 'var(--color-text-tertiary)' }}> · 활성 세션 {agent.sessions ?? 0}개</span>
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
                      // code 에이전트 manifest의 mcps=서버 목록 — 서버 수임을 정직 표기(스펙 286).
                      if ((agent.mcps || []).length) parts.push(`도구 서버 ${agent.mcps.length}개`)
                      { const liveMem = (agent.memories || []); if (liveMem.length) parts.push(`기억 ${liveMem.length}개`) }
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
                    {/* 압축 표기(스펙 286 후속) — ui 상세와 같은 문법. A2A는 상태 점(중계는 툴팁). */}
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      {agent.owner_id == null ? '공개' : '비공개'}
                      <span style={{ color: 'var(--color-text-quaternary)' }}>·</span>
                      <Tooltip title={agent.exposed?.a2a ? 'A2A 켬 — 우리 A2A 주소로 호출을 중계' : 'A2A 꺼짐 — 노출되지 않음'}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                          <span aria-label={agent.exposed?.a2a ? 'A2A 켬' : 'A2A 꺼짐'} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: agent.exposed?.a2a ? 'var(--green-6)' : 'var(--gray-5)' }} />
                          A2A
                        </span>
                      </Tooltip>
                    </span>
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
              { key: 'prompt', label: '프롬프트', children: agent.prompt || '없음' },
              {
                key: 'history',
                label: '단기 기억',
                children: agent.historyDepth ? `최근 ${agent.historyDepth}개 메시지` : '기억 안 함',
              },
              // 상설 행 + 값 '없음'(스펙 286 후속, ui 상세와 동일) — "연결 없음" 각주 대체.
              // 장기 기억(mem0) 태그만 표시 — 단기는 위 "단기 기억"(historyDepth)이 소유.
              {
                key: 'memories',
                label: '장기 기억',
                children: (agent.memories || []).length ? (
                  <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                    {agent.memories.map((m) => <Tag key={m} color="purple">{m}</Tag>)}
                  </span>
                ) : (
                  '없음'
                ),
              },
              {
                key: 'mcps',
                // manifest의 mcps=서버 목록(도구 단위 아님) — '도구 서버'로 정직 표기(스펙 286).
                label: '도구 서버',
                children: (agent.mcps || []).length ? (
                  <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                    {agent.mcps.map((m) => <Tag key={m} color="cyan">{m}</Tag>)}
                  </span>
                ) : (
                  '없음'
                ),
              },
              { key: 'sessions', label: '세션', children: <>활성 {agent.sessions ?? 0}개</> },
            ]}
          />
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
                    background: v.version === agent.activeVersion ? 'var(--color-success-bg)' : 'transparent',
                  }}
                >
                  <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', width: 64 }}>
                    {v.version}
                  </code>
                  {v.version === agent.activeVersion ? <Tag color="green">서빙 중</Tag> : <Tag>이전 배포</Tag>}
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
                    {/* 값은 상태만(사용자 지시, ui 상세와 동일) — A2A 제약은 A2A 행이 소유. */}
                    <span style={{ flex: 1, minWidth: 180 }}>
                      {agent.owner_id == null ? '공개' : '비공개'}
                    </span>
                    {canManage && (
                      <Button
                        size="small"
                        onClick={() =>
                          Modal.confirm({
                            title: agent.owner_id == null ? '비공개로 전환할까요?' : '공개로 전환할까요?',
                            content:
                              agent.owner_id == null
                                ? '비공개가 되면 소유자만 사용할 수 있고, 켜져 있던 A2A 공개는 자동으로 꺼집니다.'
                                : '공개가 되면 모든 사용자가 사용할 수 있고 A2A 공개(서버가 1홉 중계)도 켤 수 있습니다.',
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
                label: 'A2A',
                children: (
                  <ExposeSwitch
                    on={!!agent.exposed.a2a}
                    onChange={() => onToggleExpose(agent)}
                    label=""
                    onText="켬 · 우리 A2A 주소로 호출을 중계"
                    offText={agent.owner_id != null ? '공개로 전환하면 켤 수 있습니다' : '꺼짐 · 노출되지 않음'}
                    disabled={agent.owner_id != null}
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
