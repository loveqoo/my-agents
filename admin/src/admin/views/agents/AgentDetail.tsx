import { useEffect, useState } from 'react'
import { Tag, Button, Avatar, Alert, Modal, Descriptions } from 'antd'
import { Drawer, VersionHistory, ExposeSwitch } from '../../shared'
import { Icon } from '../../icons'
import { AgentMemoryPanel } from '../AgentMemoryPanel'
import type { Agent, VersionMeta } from '../../mockData'
import { displayName } from '../../naming'
import { getAgentOps, type AgentOps } from '../../../api'
import { CodeAgentDetail } from './detail/CodeAgentDetail'
import { ExternalAgentDetail } from './detail/ExternalAgentDetail'
import { PersonaStaleNote } from './PersonaStaleNote'
import { FeedbackHarvestButton } from './FeedbackHarvestButton'
import { IdRow } from './primitives'

/* 노출된 로컬(ui) 에이전트의 A2A 카드 URL(스펙 061 D7). 사용자가 "원격 에이전트 연결"에 그대로 붙여
   자기 에이전트를 A2A로 등록·테스트(dogfood)한다. connect는 백엔드가 이 URL을 **직접 self-fetch**하므로
   (프록시 `/api`를 안 거침) 백엔드 자기 절대주소여야 한다. VITE_API_BASE가 절대 URL이면 그걸, 아니면
   루프백 기본(vite 프록시 타깃 127.0.0.1:8000과 동일 · D5의 A2A_ALLOWED_HOSTS=127.0.0.1과 맞음).
   agentPk는 DB pk(agent.id) — 백엔드 라우트 `/agents/{agent_id}`가 uuid pk로 키잉한다(agentId 표시용 아님). */
export function a2aCardUrl(agentPk: string): string {
  const env = (import.meta.env.VITE_API_BASE ?? '') as string
  const origin = /^https?:\/\//.test(env) ? env.replace(/\/+$/, '') : 'http://127.0.0.1:8000'
  return `${origin}/agents/${agentPk}/.well-known/agent-card.json`
}

export function AgentDetail({
  agent,
  onClose,
  onEdit,
  onDelete,
  onClone,
  onToggleExpose,
  onSetVisibility,
  onActivate,
  onTest,
  onRevert,
  onResync,
  onNewDraft,
  onRefreshPersona,
}: {
  agent: Agent | null
  onClose: () => void
  onEdit: (a: Agent) => void
  onDelete: (a: Agent) => void
  onClone: (a: Agent) => void
  onToggleExpose: (a: Agent) => void
  onSetVisibility: (a: Agent, pub: boolean) => void
  onActivate: (a: Agent, v: VersionMeta) => void
  onTest: (a: Agent, v: VersionMeta) => void
  onRevert: (a: Agent, v: VersionMeta) => void
  onResync: (a: Agent) => void
  onNewDraft: (a: Agent) => void
  onRefreshPersona: (a: Agent) => Promise<void>
}) {
  // 버전 운영 지표(스펙 244) — 훅은 조기 return 이전(순서 불변). 로컬(ui) 에이전트만 조회,
  // 실패는 무소음(지표는 부가층 — 상세를 막지 않음).
  const [ops, setOps] = useState<AgentOps | null>(null)
  // 관리 가능 에이전트만(서버 403과 정합 — 운영 지표는 관리자·소유자 전용, codex 244 #2).
  const isLocalUi = !!agent && agent.source === 'ui' && agent.can_manage !== false
  useEffect(() => {
    setOps(null)
    if (agent && isLocalUi) {
      getAgentOps(agent.id).then(setOps).catch(() => setOps(null))
    }
  }, [agent?.id, isLocalUi])
  if (!agent) return null
  if (agent.source === 'code')
    return (
      <CodeAgentDetail
        agent={agent}
        onClose={onClose}
        onDelete={onDelete}
        onClone={onClone}
        onResync={onResync}
        onToggleExpose={onToggleExpose}
        onSetVisibility={onSetVisibility}
        onRefreshPersona={onRefreshPersona}
      />
    )
  if (agent.source === 'external')
    return (
      <ExternalAgentDetail
        agent={agent}
        onClose={onClose}
        onDelete={onDelete}
        onClone={onClone}
      />
    )
  const draft = (agent.versions || []).find((v) => v.status === 'draft')
  return (
    <Drawer
      open={!!agent}
      title={displayName(agent)}
      width={480}
      onClose={onClose}
      footer={
        // 복제는 **관리 권한 불요**(가시하면 복제 가능 — 사용≠관리, 스펙 112·120) → can_manage 밖에 항상 노출.
        <>
          <Button icon={<Icon name="copy" />} onClick={() => onClone(agent)}>
            복제
          </Button>
          {agent.can_manage === false ? (
            <span style={{ color: 'var(--color-text-tertiary)', marginLeft: 8 }}>다른 사용자 소유 — 관리 권한 없음</span>
          ) : (
            <>
              <Button danger icon={<Icon name="delete" />} onClick={() => onDelete(agent)}>
                삭제
              </Button>
              <Button type="primary" icon={<Icon name="edit" />} onClick={() => onEdit(agent)}>
                {draft ? '초안 편집' : '편집(새 초안)'}
              </Button>
            </>
          )}
        </>
      }
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <Avatar size="large" style={{ background: 'var(--gray-12)' }}>
          <Icon name="robot" />
        </Avatar>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{displayName(agent)}</div>
          <code style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>
            {agent.agentId}
          </code>
        </div>
        {agent.conformance === 'config_error' ? (
          <Tag color="red">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontWeight: 600 }}>
              <Icon name="exclamation-circle" size={11} /> 설정 실패
            </span>
          </Tag>
        ) : (
          <Tag color="green">
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              서빙 중 <code style={{ fontFamily: 'var(--font-family-code)' }}>{agent.activeVersion}</code>
            </span>
          </Tag>
        )}
      </div>
      {agent.conformance === 'config_error' ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          title="에이전트 설정 실패 — 런타임이 서빙을 거부합니다"
          description="이 에이전트는 실행 방식 설정에 문제가 있어 실행할 수 없습니다(등록되지 않았거나 형식이 맞지 않음). 담당자에게 문의하거나, 실행 방식을 기본값으로 되돌린 뒤 다시 시도하세요."
        />
      ) : null}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>활성 구성(현재 서빙 중)</span>
        <div style={{ flex: 1 }} />
        {(agent.environments || []).map((env) =>
          env === 'production' ? (
            <Tag key={env} color="geekblue">
              {env}
            </Tag>
          ) : (
            <Tag key={env}>{env}</Tag>
          )
        )}
      </div>
      <Descriptions
        column={1}
        size="small"
        items={[
          {
            key: 'model',
            label: '모델',
            children: <span style={{ fontFamily: 'var(--font-family-code)' }}>{agent.model}</span>,
          },
          { key: 'persona', label: '페르소나', children: agent.persona },
        ]}
      />
      <PersonaStaleNote agent={agent} onRefresh={onRefreshPersona} />
      <Descriptions
        column={1}
        size="small"
        items={[
          {
            key: 'memories',
            label: '메모리',
            children: (agent.memories || []).length ? (
              <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                {agent.memories.map((m) => (
                  <Tag key={m} color="purple">
                    {m}
                  </Tag>
                ))}
              </span>
            ) : (
              <span style={{ color: 'var(--color-text-tertiary)' }}>메모리 없음</span>
            ),
          },
          {
            key: 'history',
            label: '채팅 히스토리',
            children: agent.historyDepth ? `최근 ${agent.historyDepth}개 메시지` : '기억 안 함',
          },
          ...((agent.memories || []).includes('장기 기억 (mem0)')
            ? [
                {
                  key: 'vectors',
                  label: '벡터 테이블',
                  children: (agent.vectorTables || []).length ? (
                    <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                      {agent.vectorTables.map((t) => (
                        <Tag key={t} color="cyan">
                          <code style={{ fontFamily: 'var(--font-family-code)' }}>{t}</code>
                        </Tag>
                      ))}
                    </span>
                  ) : (
                    <span style={{ color: 'var(--color-text-tertiary)' }}>연결 안 함 (외부 지식 없음)</span>
                  ),
                },
              ]
            : []),
          ...((agent.memories || []).includes('장기 기억 (mem0)') && agent.source === 'ui'
            ? [{ key: 'mem0', label: '에이전트 지식 (mem0)', children: <AgentMemoryPanel agentId={agent.id} /> }]
            : []),
          {
            key: 'mcps',
            label: 'MCP',
            children: (
              <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
                {agent.mcps.map((m) => (
                  <Tag key={m} color="cyan">
                    {m}
                  </Tag>
                ))}
              </span>
            ),
          },
          { key: 'sessions', label: '세션', children: <>활성 {agent.sessions}개</> },
        ]}
      />

      {draft ? (
        <div
          style={{
            marginTop: 16,
            border: '1px solid var(--gold-3)',
            background: 'var(--gold-1)',
            borderRadius: 'var(--radius-lg)',
            padding: 14,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <Tag color="gold">초안 {draft.version}</Tag>
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', flex: 1 }}>{draft.note}</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, fontSize: 12 }}>
            {draft.config
              ? (() => {
                  const cfg = draft.config
                  const diffs: string[] = []
                  if (cfg.model !== agent.model) diffs.push('모델 → ' + cfg.model)
                  if (cfg.persona !== agent.persona) diffs.push('페르소나 → ' + cfg.persona)
                  if ((cfg.memories || []).join() !== (agent.memories || []).join()) diffs.push('메모리 변경됨')
                  if (cfg.historyDepth !== agent.historyDepth) diffs.push('채팅 히스토리 → ' + (cfg.historyDepth || 0))
                  if ((cfg.vectorTables || []).join() !== (agent.vectorTables || []).join())
                    diffs.push('벡터 테이블 변경됨')
                  const ma = (cfg.mcps || []).join(),
                    mb = agent.mcps.join()
                  if (ma !== mb) diffs.push('MCP 변경됨')
                  return diffs.length ? (
                    diffs.map((d, i) => (
                      <Tag key={i} color="geekblue">
                        {d}
                      </Tag>
                    ))
                  ) : (
                    <span style={{ color: 'var(--color-text-tertiary)' }}>활성 버전과 동일 — 편집해 변경하세요.</span>
                  )
                })()
              : null}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
            {agent.can_manage !== false && (
              <Button size="small" icon={<Icon name="edit" />} onClick={() => onEdit(agent)}>
                편집
              </Button>
            )}
            <Button size="small" type="primary" icon={<Icon name="thunderbolt" />} onClick={() => onTest(agent, draft)}>
              테스트
            </Button>
            {agent.can_manage !== false && (
              <Button size="small" icon={<Icon name="check" />} onClick={() => onActivate(agent, draft)}>
                활성화
              </Button>
            )}
          </div>
        </div>
      ) : null}

      {/* 공개 범위 전환(스펙 154 — 승격/강등). private는 A2A 불가(147)라 이 컨트롤이 A2A의 선행 조건. */}
      {agent.can_manage !== false ? (
        <div
          style={{
            marginTop: 18, padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10,
            border: '1px solid var(--color-border-secondary)', borderRadius: 'var(--radius-lg)',
            background: 'var(--gray-2)',
          }}
        >
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-text-heading)' }}>공개 범위</div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              {agent.owner_id == null
                ? 'public · 모두 도구처럼 사용 가능(A2A 켜기 가능)'
                : 'private · 소유자만 사용(A2A 불가)'}
            </div>
          </div>
          <Button
            size="small"
            onClick={() =>
              Modal.confirm({
                title: agent.owner_id == null ? '비공개(private)로 전환할까요?' : '공개(public)로 전환할까요?',
                content:
                  agent.owner_id == null
                    ? 'private가 되면 소유자만 사용할 수 있고, 켜져 있던 A2A 공개는 자동으로 꺼집니다.'
                    : 'public이 되면 모든 사용자가 이 에이전트를 도구처럼 사용할 수 있고 A2A 공개도 켤 수 있게 됩니다.',
                okText: '전환',
                cancelText: '취소',
                onOk: () => onSetVisibility(agent, agent.owner_id != null),
              })
            }
          >
            {agent.owner_id == null ? '비공개로 전환' : '공개로 전환'}
          </Button>
        </div>
      ) : null}

      <div style={{ marginTop: 10 }}>
        <ExposeSwitch
          on={!!agent.exposed.a2a}
          onChange={() => onToggleExpose(agent)}
          label="A2A로 공개"
          onText="켬 · 다른 에이전트가 호출 가능"
          offText="꺼짐 · 노출되지 않음"
        />
      </div>

      {agent.exposed.a2a ? (
        <div
          style={{
            marginTop: 10,
            padding: 14,
            border: '1px solid var(--green-3)',
            background: 'var(--green-1)',
            borderRadius: 'var(--radius-lg)',
          }}
        >
          <div
            style={{
              fontSize: 12,
              color: 'var(--color-text-tertiary)',
              marginBottom: 8,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <Icon name="global" size={12} style={{ color: 'var(--green-7)' }} />
            A2A 식별자(소비자와 공유)
          </div>
          <IdRow label="Agent ID" value={agent.agentId} />
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', margin: '2px 0 8px 84px' }}>
            불변 · 모든 환경에서 동일한 ID
          </div>
          <IdRow label="A2A 카드" value={a2aCardUrl(agent.id)} />
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', margin: '2px 0 0 84px' }}>
            이 URL을 <strong>“원격 에이전트 연결”</strong>에 그대로 붙여 등록·테스트하세요. 루프백/사설
            주소면 백엔드에 <code style={{ fontFamily: 'var(--font-family-code)' }}>A2A_ALLOWED_HOSTS=127.0.0.1</code>가 필요합니다.
          </div>
        </div>
      ) : null}

      {agent.can_manage !== false ? (
        <div
          style={{
            marginTop: 18, padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10,
            border: '1px solid var(--color-border-secondary)', borderRadius: 'var(--radius-lg)',
          }}
        >
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--color-text-heading)' }}>피드백 수확</div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              응답 피드백(👍/👎)을 초안 평가 케이스로 — 에이전트 변경 회귀 지표
            </div>
          </div>
          <FeedbackHarvestButton agentId={agent.id} />
        </div>
      ) : null}

      <div style={{ marginTop: 18 }}>
        <VersionHistory
          versions={agent.versions || []}
          onActivate={(v) => onActivate(agent, v)}
          onTest={(v) => onTest(agent, v)}
          onRevert={(v) => onRevert(agent, v)}
          onNewDraft={draft ? null : () => onNewDraft(agent)}
          ops={ops?.versions}
        />
        {/* 버전 미기록 피드백(242 이전 대화) — 정직한 분리(과거를 아는 척하지 않음). 스펙 244. */}
        {ops && (ops.unversionedUp > 0 || ops.unversionedDown > 0) && (
          <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 6 }}>
            버전 미기록 피드백 👍{ops.unversionedUp} 👎{ops.unversionedDown} (버전 기록 도입 전 대화)
          </div>
        )}
      </div>

      <div style={{ marginTop: 16 }}>
        <Alert
          type="info"
          showIcon
          title="편집은 항상 초안에 저장됩니다 — 활성 버전은 계속 서빙. 초안을 테스트한 뒤 활성화해 게시하세요(이전 버전은 롤백용으로 보관됩니다)."
        />
      </div>
    </Drawer>
  )
}
