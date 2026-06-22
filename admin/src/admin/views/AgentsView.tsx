/* my-agents admin — Agents view: list created agents, view detail, and
   create / edit / delete (composing building blocks). */
import { useState, useEffect } from 'react'
import { Tag, Button, Avatar, Select, Input, Checkbox, Switch, Modal, Alert } from 'antd'
import { Page, StatusPill, DataTable, Drawer, Desc, VersionHistory, ExposeSwitch, type Column } from '../shared'
import { Icon } from '../icons'
import {
  BLOCKS,
  ADMIN_AGENTS,
  ADMIN_SESSIONS,
  AGENT_STATUS,
  APPROVER,
  type Agent,
  type AgentConfig,
  type VersionMeta,
} from '../mockData'

/* 폼 데이터 shape — 생성/편집에서 공유. */
interface AgentFormData {
  name: string
  model: string
  persona: string
  memories: string[]
  historyDepth: number
  vectorTables: string[]
  permissions: string[]
  mcps: string[]
}

/* ---- Create / edit form (composes blocks into a version config) ---- */
function AgentForm({
  open,
  initial,
  mode,
  draftVersion,
  onCancel,
  onSave,
}: {
  open: boolean
  initial: AgentFormData | null
  mode: 'create' | 'edit'
  draftVersion: string | null
  onCancel: () => void
  onSave: (data: AgentFormData) => void
}) {
  const blocks = BLOCKS
  const blank: AgentFormData = {
    name: '',
    model: 'claude-sonnet-4',
    persona: blocks.persona.items[0].name,
    memories: [],
    historyDepth: 20,
    vectorTables: [],
    permissions: [],
    mcps: [],
  }
  const [form, setForm] = useState<AgentFormData>(blank)

  useEffect(() => {
    setForm(initial ? { ...initial } : blank)
    /* eslint-disable-next-line */
  }, [open])

  const set = <K extends keyof AgentFormData>(k: K, v: AgentFormData[K]) =>
    setForm((f) => ({ ...f, [k]: v }))
  const toggle = (k: 'memories' | 'vectorTables' | 'permissions' | 'mcps', v: string) =>
    setForm((f) => ({
      ...f,
      [k]: f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v],
    }))
  const isEdit = mode === 'edit'

  return (
    <Modal
      open={open}
      width={560}
      title={isEdit ? `초안 편집 · ${draftVersion}` : '에이전트 생성'}
      okText={isEdit ? '초안 저장' : '에이전트 생성'}
      cancelText="취소"
      onCancel={onCancel}
      onOk={() => onSave({ ...form, name: form.name.trim() || '이름 없는 에이전트' })}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '60vh', overflow: 'auto' }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 0 }}
          message={
            isEdit
              ? `변경사항은 초안 ${draftVersion}에 저장됩니다 — 활성화하기 전까지 현재 버전이 계속 서빙합니다.`
              : '에이전트의 v1 초안을 만듭니다. 테스트 후 활성화해 게시하세요.'
          }
        />
        <Field label="이름">
          <Input placeholder="예: 리서치 어시스턴트" value={form.name} onChange={(e) => set('name', e.target.value)} />
        </Field>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <Field label="모델">
            <Select
              value={form.model}
              onChange={(v) => set('model', v)}
              style={{ width: '100%' }}
              options={[
                { label: 'claude-sonnet-4', value: 'claude-sonnet-4' },
                { label: 'claude-haiku-4', value: 'claude-haiku-4' },
                { label: 'gpt-4o', value: 'gpt-4o' },
                { label: 'gpt-4o-mini', value: 'gpt-4o-mini' },
              ]}
            />
          </Field>
          <Field label="페르소나">
            <Select
              value={form.persona}
              onChange={(v) => set('persona', v)}
              style={{ width: '100%' }}
              options={blocks.persona.items.map((p) => ({ label: p.name, value: p.name }))}
            />
          </Field>
        </div>
        <Field label="메모리 타입">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {blocks.memory.items.map((m) => (
              <label
                key={m.id}
                style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 14, cursor: 'pointer' }}
              >
                <Checkbox checked={form.memories.includes(m.name)} onChange={() => toggle('memories', m.name)}>
                  <span style={{ fontWeight: 500 }}>{m.name}</span>
                </Checkbox>
                <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{m.body}</span>
              </label>
            ))}
            {form.memories.length === 0 ? (
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', fontStyle: 'italic' }}>
                메모리 없음 — 에이전트가 과거를 기억하지 않습니다(스테이트리스).
              </span>
            ) : null}
          </div>
        </Field>
        {form.memories.includes('장기·의미론적') ? (
          <Field label="벡터 테이블 (지식 소스)">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {blocks.embedding.items.map((t) => (
                <label
                  key={t.id}
                  style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 14, cursor: 'pointer' }}
                >
                  <Checkbox checked={form.vectorTables.includes(t.name)} onChange={() => toggle('vectorTables', t.name)}>
                    <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, color: 'var(--cyan-7)' }}>
                      {t.name}
                    </code>
                  </Checkbox>
                  <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                    {t.model} · {t.source}
                  </span>
                </label>
              ))}
              {form.vectorTables.length === 0 ? (
                <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', fontStyle: 'italic' }}>
                  연결된 벡터 테이블 없음 — 외부 지식 소스를 검색하지 않습니다.
                </span>
              ) : null}
            </div>
          </Field>
        ) : null}
        <Field label="채팅 히스토리">
          <Select
            value={form.historyDepth}
            onChange={(v) => set('historyDepth', v)}
            style={{ width: '100%' }}
            options={[
              { label: '기억 안 함 (0개)', value: 0 },
              { label: '최근 6개 메시지', value: 6 },
              { label: '최근 10개 메시지', value: 10 },
              { label: '최근 20개 메시지', value: 20 },
              { label: '최근 40개 메시지', value: 40 },
              { label: '최근 100개 메시지', value: 100 },
            ]}
          />
        </Field>
        <Field label="권한">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {blocks.permission.items.map((p) => {
              const a = p.approver ? APPROVER[p.approver] : APPROVER.user
              return (
                <label
                  key={p.id}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer' }}
                >
                  <Checkbox checked={form.permissions.includes(p.name)} onChange={() => toggle('permissions', p.name)}>
                    <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13 }}>{p.name}</code>
                  </Checkbox>
                  <Tag color={a.tag}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                      {a.icon ? <Icon name={a.icon} size={10} /> : null}
                      {a.label}
                    </span>
                  </Tag>
                </label>
              )
            })}
          </div>
        </Field>
        <Field label="MCP 서버">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px' }}>
            {blocks.mcp.items.map((m) => (
              <Checkbox key={m.id} checked={form.mcps.includes(m.name)} onChange={() => toggle('mcps', m.name)}>
                {m.name}
              </Checkbox>
            ))}
          </div>
        </Field>
      </div>
    </Modal>
  )
}

function Field({ label, children }: { label: React.ReactNode; children?: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontSize: 14, color: 'var(--color-text)', fontWeight: 500 }}>{label}</span>
      {children}
    </label>
  )
}

/* Resolve a permission name to its approver meta. */
function permApprover(name: string) {
  const p = (BLOCKS.permission.items || []).find((x) => x.name === name)
  return p && p.approver ? APPROVER[p.approver] : null
}
function PermTag({ name }: { name: string }) {
  const a = permApprover(name)
  if (!a) return <Tag color="geekblue">{name}</Tag>
  return (
    <Tag color={a.tag}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        {name}
        {a.icon ? <Icon name={a.icon} size={10} /> : null}
      </span>
    </Tag>
  )
}

/* ---- Detail drawer ---- */
function IdRow({ label, value }: { label: React.ReactNode; value: string }) {
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

function AgentDetail({
  agent,
  onClose,
  onEdit,
  onDelete,
  onToggleExpose,
  onActivate,
  onTest,
  onRevert,
}: {
  agent: Agent | null
  onClose: () => void
  onEdit: (a: Agent) => void
  onDelete: (a: Agent) => void
  onToggleExpose: (a: Agent) => void
  onActivate: (a: Agent, v: VersionMeta) => void
  onTest: (a: Agent, v: VersionMeta) => void
  onRevert: (a: Agent, v: VersionMeta) => void
}) {
  if (!agent) return null
  const draft = (agent.versions || []).find((v) => v.status === 'draft')
  return (
    <Drawer
      open={!!agent}
      title={agent.name}
      width={480}
      onClose={onClose}
      footer={
        <>
          <Button danger icon={<Icon name="delete" />} onClick={() => onDelete(agent)}>
            삭제
          </Button>
          <Button type="primary" icon={<Icon name="edit" />} onClick={() => onEdit(agent)}>
            {draft ? '초안 편집' : '편집(새 초안)'}
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <Avatar size="large" style={{ background: 'var(--gray-12)' }}>
          <Icon name="robot" />
        </Avatar>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{agent.name}</div>
          <code style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>
            {agent.agentId}
          </code>
        </div>
        <Tag color="green">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            서빙 중 <code style={{ fontFamily: 'var(--font-family-code)' }}>{agent.activeVersion}</code>
          </span>
        </Tag>
      </div>
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
      <Desc label="모델">
        <span style={{ fontFamily: 'var(--font-family-code)' }}>{agent.model}</span>
      </Desc>
      <Desc label="페르소나">{agent.persona}</Desc>
      <Desc label="메모리">
        {(agent.memories || []).length ? (
          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
            {agent.memories.map((m) => (
              <Tag key={m} color="purple">
                {m}
              </Tag>
            ))}
          </span>
        ) : (
          <span style={{ color: 'var(--color-text-tertiary)' }}>메모리 없음 (스테이트리스)</span>
        )}
      </Desc>
      <Desc label="채팅 히스토리">{agent.historyDepth ? `최근 ${agent.historyDepth}개 메시지` : '기억 안 함'}</Desc>
      {(agent.memories || []).includes('장기·의미론적') ? (
        <Desc label="벡터 테이블">
          {(agent.vectorTables || []).length ? (
            agent.vectorTables.map((t) => (
              <Tag key={t} color="cyan">
                <code style={{ fontFamily: 'var(--font-family-code)' }}>{t}</code>
              </Tag>
            ))
          ) : (
            <span style={{ color: 'var(--color-text-tertiary)' }}>연결 안 함 (외부 지식 없음)</span>
          )}
        </Desc>
      ) : null}
      <Desc label="권한">
        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
          {agent.permissions.map((p) => (
            <PermTag key={p} name={p} />
          ))}
        </span>
      </Desc>
      <Desc label="MCP">
        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
          {agent.mcps.map((m) => (
            <Tag key={m} color="cyan">
              {m}
            </Tag>
          ))}
        </span>
      </Desc>
      <Desc label="세션">활성 {agent.sessions}개</Desc>

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
                  const pa = (cfg.permissions || []).join(),
                    pb = agent.permissions.join()
                  if (pa !== pb) diffs.push('권한 변경됨')
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
            <Button size="small" icon={<Icon name="edit" />} onClick={() => onEdit(agent)}>
              편집
            </Button>
            <Button size="small" type="primary" icon={<Icon name="thunderbolt" />} onClick={() => onTest(agent, draft)}>
              테스트
            </Button>
            <Button size="small" icon={<Icon name="check" />} onClick={() => onActivate(agent, draft)}>
              활성화
            </Button>
          </div>
        </div>
      ) : null}

      <div style={{ marginTop: 18 }}>
        <ExposeSwitch
          on={!!agent.exposed.a2a}
          onChange={() => onToggleExpose(agent)}
          label="A2A로 공개"
          onText="공개 · 다른 에이전트가 호출 가능"
          offText="비공개 · 노출되지 않음"
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
          {(agent.environments || ['production']).map((env) => (
            <IdRow key={env} label={env} value={'a2a://my-agents.' + env + '.local/' + agent.agentId} />
          ))}
          <IdRow label="Agent Card" value={'https://my-agents.local/.well-known/agent.json?id=' + agent.agentId} />
        </div>
      ) : null}

      <div style={{ marginTop: 18 }}>
        <VersionHistory
          versions={agent.versions || []}
          onActivate={(v) => onActivate(agent, v)}
          onTest={(v) => onTest(agent, v)}
          onRevert={(v) => onRevert(agent, v)}
          onNewDraft={draft ? null : () => onEdit(agent)}
        />
      </div>

      <div style={{ marginTop: 16 }}>
        <Alert
          type="info"
          showIcon
          message="편집은 항상 초안에 저장됩니다 — 활성 버전은 계속 서빙. 초안을 테스트한 뒤 활성화해 게시하세요(이전 버전은 롤백용으로 보관됩니다)."
        />
      </div>
    </Drawer>
  )
}

/* ---- Main view ---- */
export default function AgentsView() {
  const [agents, setAgents] = useState<Agent[]>(ADMIN_AGENTS)
  const [detailId, setDetailId] = useState<string | null>(null)
  const detail = agents.find((a) => a.id === detailId) || null
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<{ agent: Agent; version: string | null } | null>(null)
  const [confirmDel, setConfirmDel] = useState<Agent | null>(null)
  const [exposeOff, setExposeOff] = useState<{ agent: Agent; count: number } | null>(null) // agent pending expose-off confirm
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 2400)
    return () => clearTimeout(t)
  }, [toast])

  const configOf = (a: Agent): AgentConfig => ({
    model: a.model,
    persona: a.persona,
    memories: [...(a.memories || [])],
    historyDepth: a.historyDepth,
    vectorTables: [...(a.vectorTables || [])],
    permissions: [...a.permissions],
    mcps: [...a.mcps],
  })
  const draftOf = (a: Agent) => (a.versions || []).find((v) => v.status === 'draft')
  const openCreate = () => {
    setEditing(null)
    setFormOpen(true)
  }
  // Edit always works on a DRAFT: seed from the existing draft if present, else from active.
  const openEdit = (a: Agent) => {
    setDetailId(null)
    const d = draftOf(a)
    setEditing({ agent: a, version: d ? d.version : null })
    setFormOpen(true)
  }

  // ---- versioning + expose ----
  const nextVersion = (versions: VersionMeta[]) => {
    const max = versions.reduce(
      (n, v) => Math.max(n, parseInt(String(v.version).replace(/\D/g, ''), 10) || 0),
      0
    )
    return 'v' + (max + 1)
  }
  const setExpose = (id: string, val: boolean) =>
    setAgents((as) => as.map((a) => (a.id === id ? { ...a, exposed: { ...a.exposed, a2a: val } } : a)))
  const liveSessions = (id: string) =>
    (ADMIN_SESSIONS || []).filter((s) => s.agentId === id && ['active', 'running', 'awaiting'].includes(s.status))
  const toggleExpose = (agent: Agent) => {
    if (!agent.exposed.a2a) {
      setExpose(agent.id, true)
      setToast(`${agent.name} — A2A 공개됨`)
      return
    }
    // turning OFF
    const live = liveSessions(agent.id)
    if (live.length === 0) {
      setExpose(agent.id, false)
      setToast(`${agent.name} — A2A 비공개됨`)
      return
    }
    setExposeOff({ agent, count: live.length })
  }
  const deprecate = () => {
    if (!exposeOff) return
    const { agent } = exposeOff
    setExpose(agent.id, false)
    liveSessions(agent.id).forEach((s) => {
      s.status = 'draining'
      s.lastActivity = '드레이닝…'
    })
    setToast(`${agent.name} 사용 중단 — 세션 ${exposeOff.count}개 드레이닝 중, 신규 세션 차단`)
    setExposeOff(null)
  }
  const revokeNow = () => {
    if (!exposeOff) return
    const { agent } = exposeOff
    setExpose(agent.id, false)
    liveSessions(agent.id).forEach((s) => {
      s.status = 'completed'
      s.lastActivity = '종료됨'
    })
    setAgents((as) => as.map((a) => (a.id === agent.id ? { ...a, sessions: 0 } : a)))
    setToast(`${agent.name} — A2A 철회, 세션 ${exposeOff.count}개 종료`)
    setExposeOff(null)
  }
  const activateVersion = (agent: Agent, v: VersionMeta) => {
    setAgents((as) =>
      as.map((a) => {
        if (a.id !== agent.id) return a
        const target = a.versions.find((x) => x.version === v.version)
        const cfg: AgentConfig = (target && target.config) || {}
        const versions = a.versions.map((x) =>
          x.version === v.version
            ? { ...x, status: 'active' as const }
            : x.status === 'active'
              ? { ...x, status: 'archived' as const }
              : x
        )
        // promote the version's config to the agent's serving (top-level) config.
        return {
          ...a,
          activeVersion: v.version,
          versions,
          model: cfg.model || a.model,
          persona: cfg.persona || a.persona,
          memories: cfg.memories ? [...cfg.memories] : a.memories,
          historyDepth: cfg.historyDepth != null ? cfg.historyDepth : a.historyDepth,
          vectorTables: cfg.vectorTables ? [...cfg.vectorTables] : a.vectorTables,
          permissions: cfg.permissions ? [...cfg.permissions] : a.permissions,
          mcps: cfg.mcps ? [...cfg.mcps] : a.mcps,
        }
      })
    )
    setToast(`${agent.name} ${v.version} 활성화됨 — 서빙 시작`)
  }
  const newDraft = (agent: Agent) => {
    setAgents((as) =>
      as.map((a) => {
        if (a.id !== agent.id) return a
        const ver = nextVersion(a.versions)
        return {
          ...a,
          versions: [
            { version: ver, status: 'draft' as const, createdAt: '2026-06-21', note: '' + a.activeVersion + '에서 포크한 초안' },
            ...a.versions,
          ],
        }
      })
    )
    setToast(`${agent.name} 새 초안 생성됨`)
  }
  const testVersion = (agent: Agent, v: VersionMeta) =>
    setToast(`${agent.name} ${v.version}(초안 구성) 테스트 — 디버그 콘솔을 열세요`)
  const revertToDraft = (agent: Agent, v: VersionMeta) => {
    const existing = agent.versions.find((x) => x.status === 'draft')
    if (existing && existing.version !== v.version) {
      setToast(`이미 초안(${existing.version})이 있습니다 — 먼저 활성화하거나 제거하세요`)
      return
    }
    // 활성 버전을 되돌리려면 승격할 보관(archived) 버전이 있어야 한다.
    // 없으면 활성 버전이 사라져 서빙 대상이 없어지므로 중단한다.
    if (v.status === 'active' && !agent.versions.some((x) => x.status === 'archived')) {
      setToast(`되돌릴 수 없습니다 — 활성 버전이 유일합니다(승격할 이전 버전 없음)`)
      return
    }
    setAgents((as) =>
      as.map((a) => {
        if (a.id !== agent.id) return a
        const wasActive = v.status === 'active'
        let versions = a.versions.map((x) => (x.version === v.version ? { ...x, status: 'draft' as const } : x))
        let activeVersion = a.activeVersion
        let top: Partial<Agent> = {}
        if (wasActive) {
          const cand = versions.find((x) => x.status === 'archived')
          if (cand) {
            versions = versions.map((x) => (x.version === cand.version ? { ...x, status: 'active' as const } : x))
            activeVersion = cand.version
            const cfg: AgentConfig = cand.config || {}
            top = {
              model: cfg.model || a.model,
              persona: cfg.persona || a.persona,
              memories: cfg.memories ? [...cfg.memories] : a.memories,
              historyDepth: cfg.historyDepth != null ? cfg.historyDepth : a.historyDepth,
              vectorTables: cfg.vectorTables ? [...cfg.vectorTables] : a.vectorTables,
              permissions: cfg.permissions ? [...cfg.permissions] : a.permissions,
              mcps: cfg.mcps ? [...cfg.mcps] : a.mcps,
            }
          }
        }
        return { ...a, versions, activeVersion, ...top }
      })
    )
    setToast(`${v.version} 초안으로 되돌림${v.status === 'active' ? ' — 이전 버전으로 롤백' : ''}`)
  }

  const save = (data: AgentFormData) => {
    const config: AgentConfig = {
      model: data.model,
      persona: data.persona,
      memories: data.memories,
      historyDepth: data.historyDepth,
      vectorTables: data.vectorTables,
      permissions: data.permissions,
      mcps: data.mcps,
    }
    if (editing) {
      // Save into a DRAFT version (create one if none exists). Active keeps serving.
      setAgents((as) =>
        as.map((a) => {
          if (a.id !== editing.agent.id) return a
          let versions: VersionMeta[]
          const existing = a.versions.find((v) => v.status === 'draft')
          if (existing) {
            versions = a.versions.map((v) =>
              v.status === 'draft' ? { ...v, config, note: 'Edited ' + new Date().toISOString().slice(0, 10) } : v
            )
          } else {
            const ver = nextVersion(a.versions)
            versions = [
              { version: ver, status: 'draft', createdAt: '2026-06-21', note: 'Draft from ' + a.activeVersion, config },
              ...a.versions,
            ]
          }
          return { ...a, name: data.name, versions }
        })
      )
      setToast(`초안에 저장됨 — 활성화하면 게시됩니다`)
    } else {
      const id = 'ag-' + Date.now()
      const agentId = 'agt_' + Math.random().toString(36).slice(2, 8)
      const created: Agent = {
        id,
        name: data.name,
        agentId,
        environments: ['sandbox'],
        status: 'idle',
        sessions: 0,
        created: '2026-06-21',
        exposed: { a2a: false },
        model: data.model,
        persona: data.persona,
        memories: data.memories,
        historyDepth: data.historyDepth,
        vectorTables: data.vectorTables,
        permissions: data.permissions,
        mcps: data.mcps,
        activeVersion: 'v1',
        versions: [{ version: 'v1', status: 'draft', createdAt: '2026-06-21', note: '초기 초안', config }],
      }
      setAgents((as) => [created, ...as])
      setToast(`"${data.name}" 생성됨 — v1 초안, 테스트 후 활성화`)
    }
    setFormOpen(false)
    setEditing(null)
  }

  const doDelete = () => {
    if (!confirmDel) return
    const target = confirmDel
    setAgents((as) => as.filter((a) => a.id !== target.id))
    setToast(`"${target.name}" 삭제됨`)
    setConfirmDel(null)
    setDetailId(null)
  }

  const columns: Column<Agent>[] = [
    {
      key: 'name',
      title: '에이전트',
      render: (a) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Avatar size="small" style={{ background: 'var(--gray-12)' }}>
            <Icon name="robot" size={14} />
          </Avatar>
          <div>
            <div style={{ fontWeight: 500, color: 'var(--color-text-heading)' }}>{a.name}</div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>
              {a.model}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: 'persona',
      title: '페르소나',
      render: (a) => <span style={{ color: 'var(--color-text-secondary)' }}>{a.persona}</span>,
    },
    {
      key: 'mcps',
      title: 'MCP',
      render: (a) => (
        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4 }}>
          {a.mcps.map((m) => (
            <Tag key={m} color="cyan">
              {m}
            </Tag>
          ))}
        </span>
      ),
    },
    {
      key: 'version',
      title: '버전',
      width: 110,
      render: (a) => {
        const draft = (a.versions || []).find((v) => v.status === 'draft')
        return (
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, color: 'var(--color-text-heading)' }}>
              {a.activeVersion}
            </code>
            {draft ? <Tag color="gold">+초안</Tag> : null}
          </span>
        )
      },
    },
    {
      key: 'exposed',
      title: '공개',
      width: 130,
      render: (a) => (
        <span onClick={(e) => e.stopPropagation()} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <Switch size="small" checked={!!a.exposed.a2a} onChange={() => toggleExpose(a)} />
          <span style={{ fontSize: 12, color: a.exposed.a2a ? 'var(--color-success)' : 'var(--color-text-tertiary)' }}>
            {a.exposed.a2a ? 'A2A' : '꺼짐'}
          </span>
        </span>
      ),
    },
    {
      key: 'status',
      title: '상태',
      width: 100,
      render: (a) => {
        const st = AGENT_STATUS[a.status]
        return <StatusPill color={st.color || 'var(--gray-6)'} label={st.label} />
      },
    },
    {
      key: 'actions',
      title: '',
      width: 96,
      align: 'right',
      render: (a) => (
        <span onClick={(e) => e.stopPropagation()} style={{ display: 'inline-flex', gap: 2 }}>
          <Button type="text" size="small" icon={<Icon name="edit" />} onClick={() => openEdit(a)} />
          <Button type="text" size="small" danger icon={<Icon name="delete" />} onClick={() => setConfirmDel(a)} />
        </span>
      ),
    },
  ]

  return (
    <Page
      title="에이전트"
      subtitle={`빌딩 블록으로 구성한 에이전트 ${agents.length}개`}
      actions={
        <Button type="primary" icon={<Icon name="plus" />} onClick={openCreate}>
          새 에이전트
        </Button>
      }
    >
      <DataTable columns={columns} rows={agents} onRowClick={(a) => setDetailId(a.id)} />

      <AgentDetail
        agent={detail}
        onClose={() => setDetailId(null)}
        onEdit={openEdit}
        onDelete={setConfirmDel}
        onToggleExpose={toggleExpose}
        onActivate={activateVersion}
        onTest={testVersion}
        onRevert={revertToDraft}
      />
      <AgentForm
        open={formOpen}
        mode={editing ? 'edit' : 'create'}
        draftVersion={
          editing
            ? draftOf(editing.agent)
              ? draftOf(editing.agent)!.version
              : nextVersion(editing.agent.versions)
            : null
        }
        initial={
          editing
            ? (() => {
                const a = editing.agent
                const d = draftOf(a)
                const c: AgentConfig = d ? d.config || configOf(a) : configOf(a)
                return {
                  name: a.name,
                  model: c.model || a.model,
                  persona: c.persona || a.persona,
                  memories: [...(c.memories || [])],
                  historyDepth: c.historyDepth != null ? c.historyDepth : a.historyDepth,
                  vectorTables: [...(c.vectorTables || [])],
                  permissions: [...(c.permissions || [])],
                  mcps: [...(c.mcps || [])],
                }
              })()
            : null
        }
        onCancel={() => {
          setFormOpen(false)
          setEditing(null)
        }}
        onSave={save}
      />

      <Modal
        open={!!confirmDel}
        title="에이전트를 삭제할까요?"
        okText="삭제"
        cancelText="취소"
        onCancel={() => setConfirmDel(null)}
        onOk={doDelete}
      >
        {confirmDel ? (
          <div>
            <b>{confirmDel.name}</b> 및 공개 엔드포인트가 영구 삭제됩니다. 진행 중인 세션도 종료됩니다. 되돌릴 수
            없습니다.
          </div>
        ) : null}
      </Modal>

      <Modal
        open={!!exposeOff}
        title="A2A 공개를 끌까요?"
        width={460}
        onCancel={() => setExposeOff(null)}
        footer={
          exposeOff ? (
            <>
              <Button onClick={() => setExposeOff(null)}>취소</Button>
              <Button icon={<Icon name="pause-circle" />} onClick={deprecate}>
                사용 중단(드레인)
              </Button>
              <Button danger type="primary" icon={<Icon name="close" />} onClick={revokeNow}>
                즉시 철회
              </Button>
            </>
          ) : null
        }
      >
        {exposeOff ? (
          <div>
            <div style={{ marginBottom: 12 }}>
              <b>{exposeOff.agent.name}</b>에 라이브 A2A 세션이 <b>{exposeOff.count}</b>개 있습니다. 오프라인 방식을
              선택하세요:
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
              <div style={{ display: 'flex', gap: 8 }}>
                <Icon name="pause-circle" size={15} style={{ color: 'var(--volcano-6)', marginTop: 2, flex: 'none' }} />
                <span>
                  <b>사용 중단(드레인)</b> — 신규 세션을 막고, 진행 중인 {exposeOff.count}개를 끝난 뒤 비공개로 전환.
                  소비자에게 가장 안전.
                </span>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Icon name="close-circle" size={15} style={{ color: 'var(--color-error)', marginTop: 2, flex: 'none' }} />
                <span>
                  <b>즉시 철회</b> — 엔드포인트를 즉시 차단; {exposeOff.count}개 세션이 종료되고 외부 호출자는 오류를
                  받습니다.
                </span>
              </div>
            </div>
          </div>
        ) : null}
      </Modal>

      {toast ? (
        <div
          style={{
            position: 'absolute',
            top: 16,
            left: 0,
            right: 0,
            display: 'flex',
            justifyContent: 'center',
            zIndex: 1100,
            pointerEvents: 'none',
          }}
        >
          <div style={{ pointerEvents: 'auto' }}>
            <Alert type="success" showIcon message={toast} />
          </div>
        </div>
      ) : null}
    </Page>
  )
}
