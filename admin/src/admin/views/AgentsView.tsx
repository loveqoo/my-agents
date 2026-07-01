/* my-agents admin — Agents view: list created agents, view detail, and
   create / edit / delete (composing building blocks). */
import { useState, useEffect, useRef } from 'react'
import { Tag, Button, Avatar, Select, Input, Checkbox, Switch, Slider, Tooltip, Modal, Alert, message } from 'antd'
import { Page, StatusPill, DataTable, Drawer, Desc, VersionHistory, ExposeSwitch, type Column } from '../shared'
import { notifyAgentsChanged } from '../../agentsBus'
import { Icon } from '../icons'
import { AgentMemoryPanel } from './AgentMemoryPanel'
import {
  BLOCKS,
  AGENT_STATUS,
  AGENT_SOURCE,
  AGENT_CONFORMANCE,
  APPROVER,
  type Agent,
  type AgentConfig,
  type BlockCategory,
  type VersionMeta,
} from '../mockData'
import {
  getBlocks,
  listAgents,
  createAgent,
  updateAgent,
  deleteAgent,
  activateVersion as apiActivateVersion,
  revertVersion as apiRevertVersion,
  forkVersion as apiForkVersion,
  exposeAgent,
  connectAgent as apiConnectAgent,
  resyncAgent,
  listModels,
  listCollections,
  type Model,
  type Collection,
} from '../../api'

/* 폼 데이터 shape — 생성/편집에서 공유. */
interface AgentFormData {
  name: string
  model: string
  persona: string
  temperature: number | null // null=자동(모델 등록값), 수동이면 0–2(스펙 077)
  memories: string[]
  historyDepth: number
  persistHistory: boolean
  vectorTables: string[]
  permissions: string[]
  mcps: string[]
}

/* 빈 폼 기본값 — persona는 로드된 blocks에서, model은 등록된 첫 chat 모델에서
   계산한다(둘 다 없으면 빈 값). 가상 모델명 하드코딩 금지(스펙 023). */
function blankForm(blocks: Record<string, BlockCategory>, models: Model[]): AgentFormData {
  return {
    name: '',
    model: models.find((m) => m.kind === 'chat')?.name ?? '',
    persona: blocks.persona?.items?.[0]?.name ?? '',
    temperature: null,
    memories: [],
    historyDepth: 20,
    persistHistory: true,
    vectorTables: [],
    permissions: [],
    mcps: [],
  }
}

/* ---- Create / edit form (composes blocks into a version config) ---- */
function AgentForm({
  open,
  initial,
  mode,
  draftVersion,
  blocks,
  models,
  collections,
  onCancel,
  onSave,
}: {
  open: boolean
  initial: AgentFormData | null
  mode: 'create' | 'edit'
  draftVersion: string | null
  blocks: Record<string, BlockCategory>
  models: Model[]
  collections: Collection[]
  onCancel: () => void
  onSave: (data: AgentFormData) => void
}) {
  const [form, setForm] = useState<AgentFormData>(() => initial ? { ...initial } : blankForm(blocks, models))

  useEffect(() => {
    setForm(initial ? { ...initial } : blankForm(blocks, models))
    /* eslint-disable-next-line */
  }, [open])

  // /blocks가 폼을 연 뒤 늦게 도착하면 생성 모드의 빈 persona를 첫 항목으로 채운다
  // (페르소나 없는 에이전트 생성 방지).
  useEffect(() => {
    const first = blocks.persona?.items?.[0]?.name
    if (open && mode === 'create' && first) {
      setForm((f) => (f.persona ? f : { ...f, persona: first }))
    }
  }, [open, mode, blocks])

  // 등록 모델(/models)이 폼을 연 뒤 늦게 도착하면 생성 모드의 빈 model을 첫 등록
  // chat 모델로 채운다(가상 모델명 폴백 방지 — persona와 동일 패턴).
  useEffect(() => {
    const first = models.find((m) => m.kind === 'chat')?.name
    if (open && mode === 'create' && first) {
      setForm((f) => (f.model ? f : { ...f, model: first }))
    }
  }, [open, mode, models])

  const set = <K extends keyof AgentFormData>(k: K, v: AgentFormData[K]) =>
    setForm((f) => ({ ...f, [k]: v }))
  const toggle = (k: 'memories' | 'vectorTables' | 'permissions' | 'mcps', v: string) =>
    setForm((f) => ({
      ...f,
      [k]: f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v],
    }))
  const isEdit = mode === 'edit'

  // 등록된 chat 모델로 옵션 구성. 목록이 비었거나 현재 model이 목록에 없으면
  // 현재 값을 옵션에 보존해 편집 시 선택이 사라지지 않게 한다.
  const modelOptions = models.map((m) => ({ label: m.name, value: m.name }))
  if (form.model && !modelOptions.some((o) => o.value === form.model)) {
    modelOptions.push({ label: form.model, value: form.model })
  }

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
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 200px), 1fr))', gap: 16 }}>
          <Field label="모델">
            <Select
              value={form.model}
              onChange={(v) => set('model', v)}
              style={{ width: '100%' }}
              options={modelOptions}
            />
          </Field>
          <Field label="페르소나">
            <Select
              value={form.persona}
              onChange={(v) => set('persona', v)}
              style={{ width: '100%' }}
              options={(blocks.persona?.items ?? []).map((p) => ({ label: p.name, value: p.name }))}
            />
          </Field>
        </div>
        {/* 온도 — 에이전트 영속 필드(스펙 077). 자동(끔)=모델 등록 기본값, 수동=0–2 저장.
            플그 오버라이드의 Temperature와 동일 UX로 대칭. */}
        <Field label="Temperature">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Tooltip title="끄면 모델 등록 기본값(자동)">
              <Switch
                size="small"
                checked={form.temperature != null}
                onChange={(on) => set('temperature', on ? 0.7 : null)}
              />
            </Tooltip>
            <Slider
              min={0}
              max={2}
              step={0.1}
              disabled={form.temperature == null}
              value={form.temperature ?? 0.7}
              onChange={(v) => set('temperature', v)}
              style={{ flex: 1 }}
            />
            <span style={{ width: 32, textAlign: 'right', fontFamily: 'var(--font-family-code)', fontSize: 13 }}>
              {form.temperature == null ? '—' : form.temperature.toFixed(1)}
            </span>
          </div>
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            {form.temperature == null ? '자동 — 모델 등록 기본값을 사용합니다.' : '에이전트에 저장됩니다(세션마다 동일).'}
          </span>
        </Field>
        <Field label="메모리 타입">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(blocks.memory?.items ?? []).map((m) => (
              <Checkbox
                key={m.id}
                checked={form.memories.includes(m.name)}
                onChange={() => toggle('memories', m.name)}
                style={{ alignItems: 'flex-start', marginInlineStart: 0 }}
              >
                <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ fontSize: 14, fontWeight: 500 }}>{m.name}</span>
                  <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{m.body}</span>
                </span>
              </Checkbox>
            ))}
            {form.memories.length === 0 ? (
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', fontStyle: 'italic' }}>
                메모리 없음 — 에이전트가 과거를 기억하지 않습니다(스테이트리스).
              </span>
            ) : null}
          </div>
        </Field>
        {/* RAG 지식 소스(스펙 037) — 실 컬렉션. mem0 장기기억과 독립(RAG ≠ mem0). */}
        <Field label="지식 소스 (RAG 컬렉션)">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {collections.map((c) => (
              <Checkbox
                key={c.id}
                checked={form.vectorTables.includes(c.name)}
                onChange={() => toggle('vectorTables', c.name)}
                style={{ alignItems: 'flex-start', marginInlineStart: 0 }}
              >
                <span style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, color: 'var(--cyan-7)' }}>
                    {c.name}
                  </code>
                  <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                    {c.embedding_model_name} · 청크 {c.chunk_count}개
                  </span>
                </span>
              </Checkbox>
            ))}
            {collections.length === 0 ? (
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', fontStyle: 'italic' }}>
                컬렉션 없음 — 'RAG 컬렉션' 메뉴에서 먼저 문서를 적재하세요.
              </span>
            ) : form.vectorTables.length === 0 ? (
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', fontStyle: 'italic' }}>
                연결된 컬렉션 없음 — 에이전트가 문서를 검색하지 않습니다.
              </span>
            ) : null}
          </div>
        </Field>
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
        <Field label="대화 저장">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Switch checked={form.persistHistory} onChange={(v) => set('persistHistory', v)} />
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              {form.persistHistory
                ? '대화를 DB에 저장 (세션·인스펙터·재개)'
                : '윈도우 모드 — 저장 안 함 (가벼움·프라이버시, 사후 기록 없음)'}
            </span>
          </div>
        </Field>
        <Field label="권한">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(blocks.permission?.items ?? []).map((p) => {
              const a = p.approver ? APPROVER[p.approver] : APPROVER.user
              return (
                <Checkbox
                  key={p.id}
                  checked={form.permissions.includes(p.name)}
                  onChange={() => toggle('permissions', p.name)}
                  style={{ marginInlineStart: 0 }}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                    <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13 }}>{p.name}</code>
                    <Tag color={a.tag}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                        {a.icon ? <Icon name={a.icon} size={10} /> : null}
                        {a.label}
                      </span>
                    </Tag>
                  </span>
                </Checkbox>
              )
            })}
          </div>
        </Field>
        <Field label="MCP 서버">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px' }}>
            {(blocks.mcp?.items ?? []).map((m) => (
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

/* 노출된 로컬(ui) 에이전트의 A2A 카드 URL(스펙 061 D7). 사용자가 "원격 에이전트 연결"에 그대로 붙여
   자기 에이전트를 A2A로 등록·테스트(dogfood)한다. connect는 백엔드가 이 URL을 **직접 self-fetch**하므로
   (프록시 `/api`를 안 거침) 백엔드 자기 절대주소여야 한다. VITE_API_BASE가 절대 URL이면 그걸, 아니면
   루프백 기본(vite 프록시 타깃 127.0.0.1:8000과 동일 · D5의 A2A_ALLOWED_HOSTS=127.0.0.1과 맞음).
   agentPk는 DB pk(agent.id) — 백엔드 라우트 `/agents/{agent_id}`가 uuid pk로 키잉한다(agentId 표시용 아님). */
function a2aCardUrl(agentPk: string): string {
  const env = (import.meta.env.VITE_API_BASE ?? '') as string
  const origin = /^https?:\/\//.test(env) ? env.replace(/\/+$/, '') : 'http://127.0.0.1:8000'
  return `${origin}/agents/${agentPk}/.well-known/agent-card.json`
}

/* ---- 원격 에이전트 연결 — URL 하나로 백엔드가 A2A 카드 fetch·검증·provenance 자동분류(스펙 057) ----
   등록 진입점 단일화. 프론트는 매니페스트를 날조하지 않는다 — URL·토큰만 받아 백엔드(`POST /agents/connect`)에
   위임하면, 카드의 my-agents 확장 유무로 source가 정해진다(있으면 우리가 배포한 SDK=code, 없으면 제3자=external). */
function ConnectAgentModal({
  open,
  onCancel,
  onConnect,
}: {
  open: boolean
  onCancel: () => void
  onConnect: (data: { url: string; token: string }) => Promise<void>
}) {
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (open) {
      setUrl('')
      setToken('')
      setSubmitting(false)
    }
  }, [open])

  const canSubmit = /^https?:\/\/.+/.test(url.trim()) && !submitting
  const submit = async () => {
    setSubmitting(true)
    try {
      await onConnect({ url: url.trim(), token: token.trim() })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open={open}
      width={560}
      title="원격 에이전트 연결"
      onCancel={onCancel}
      footer={
        <>
          <Button onClick={onCancel}>취소</Button>
          <Button type="primary" icon={<Icon name="check" />} loading={submitting} disabled={!canSubmit} onClick={submit}>
            연결
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 0 }}
          message="A2A 에이전트의 URL 하나만 입력하세요. 서버가 카드를 가져와(well-known 관례 포함) 검증하고, 우리가 배포한 SDK 에이전트인지(코드) 제3자인지(외부) 자동으로 판별합니다."
        />
        <Field label="에이전트 URL">
          <Input
            prefix={<Icon name="global" />}
            placeholder="https://agents.acme.example/translate  (또는 /.well-known/agent-card.json)"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onPressEnter={() => canSubmit && submit()}
          />
        </Field>
        <Field label="액세스 토큰 (선택)">
          <Input
            type="password"
            prefix={<Icon name="key" />}
            placeholder="호출 시 Bearer 인증이 필요하면 입력 (없으면 비워두세요)"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </Field>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          URL은 카드 문서 또는 서비스 베이스를 가리킬 수 있습니다. 베이스면 서버가 `/.well-known/agent-card.json`을 탐색합니다.
        </span>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          로컬/사설 endpoint(127.0.0.1 · 10.x · 192.168.x · ::1)는 SSRF 보호로 기본 차단됩니다 — 서버 환경변수{' '}
          <code>A2A_ALLOWED_HOSTS</code>에 해당 호스트를 추가(쉼표구분)하고 API를 재기동해야 호출됩니다. 내 로컬 에이전트를
          A2A로 노출해 테스트할 때 필요합니다(예: <code>A2A_ALLOWED_HOSTS=127.0.0.1</code>).
        </span>
      </div>
    </Modal>
  )
}

/* ---- 읽기 전용 구성 행(코드 에이전트 상세에서 사용) ---- */
function ReadonlyConfig({ agent }: { agent: Agent }) {
  return (
    <>
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
      <Desc label="권한">
        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
          {(agent.permissions || []).map((p) => (
            <PermTag key={p} name={p} />
          ))}
        </span>
      </Desc>
      <Desc label="MCP">
        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6 }}>
          {(agent.mcps || []).map((m) => (
            <Tag key={m} color="cyan">
              {m}
            </Tag>
          ))}
        </span>
      </Desc>
      <Desc label="세션">활성 {agent.sessions}개</Desc>
    </>
  )
}

/* ---- Code-defined agent detail (read-only; config owned by the deployed code) ---- */
function CodeAgentDetail({
  agent,
  onClose,
  onDelete,
  onResync,
}: {
  agent: Agent
  onClose: () => void
  onDelete: (a: Agent) => void
  onResync: (a: Agent) => void
}) {
  return (
    <Drawer
      open={!!agent}
      title={agent.name}
      width={480}
      onClose={onClose}
      footer={
        <Button danger icon={<Icon name="delete" />} onClick={() => onDelete(agent)}>
          등록 해제
        </Button>
      }
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <Avatar size="large" style={{ background: 'var(--geekblue-1)', color: 'var(--geekblue-7)' }}>
          <Icon name="code" />
        </Avatar>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
            {agent.name}
            <Tag color="geekblue">
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <Icon name="code" size={11} />
                Code
              </span>
            </Tag>
          </div>
          <code style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>
            {agent.agentId}
          </code>
        </div>
        <Tag color="green">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            서빙 중 <code style={{ fontFamily: 'var(--font-family-code)' }}>{agent.commit || agent.activeVersion}</code>
          </span>
        </Tag>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 14 }}
        message="SDK로 코드 정의해 원격 엔드포인트에서 실행되는 에이전트입니다. 구성은 코드가 소유하므로 콘솔에서는 읽기 전용입니다 — 변경하려면 코드를 수정해 다시 배포한 뒤 동기화하세요."
      />

      <ReadonlyConfig agent={agent} />

      <div
        style={{
          marginTop: 16,
          padding: 14,
          border: '1px solid var(--geekblue-3)',
          background: 'var(--geekblue-1)',
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
          <Icon name="code" size={12} style={{ color: 'var(--geekblue-7)' }} />
          배포 / 연결
        </div>
        <IdRow label="Endpoint" value={agent.endpoint || '—'} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
          <span style={{ width: 84, flex: 'none', fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            Access token
          </span>
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
            {agent.token || '—'}
          </code>
          <Icon name="key" size={13} style={{ color: 'var(--color-text-tertiary)', flex: 'none' }} />
        </div>
        <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', margin: '2px 0 8px 84px' }}>
          마스킹 표시 · 콘솔에 평문 저장 안 함
        </div>
        <Desc label="런타임" width={84}>
          <span style={{ fontFamily: 'var(--font-family-code)', fontSize: 13 }}>{agent.runtime || '—'}</span>
        </Desc>
        <Desc label="소스" width={84}>
          <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13 }}>
            {agent.repo}
            {agent.commit ? '@' + agent.commit : ''}
          </code>
        </Desc>
        <Desc label="등록일" width={84}>
          {agent.registeredAt || '—'}
        </Desc>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
          <span style={{ flex: 1, fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            마지막 동기화 · {agent.lastSync || '—'}
          </span>
          <Button size="small" icon={<Icon name="sync" />} onClick={() => onResync(agent)}>
            재동기화
          </Button>
        </div>
      </div>

      <div style={{ marginTop: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', marginBottom: 10 }}>
          배포 히스토리
        </div>
        <div
          style={{
            border: '1px solid var(--color-border-secondary)',
            borderRadius: 'var(--radius-lg)',
            overflow: 'hidden',
          }}
        >
          {(agent.versions || []).map((v, i) => (
            <div
              key={v.version}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 14px',
                borderTop: i ? '1px solid var(--color-border-secondary)' : 'none',
                background: v.status === 'active' ? 'var(--color-success-bg)' : 'transparent',
              }}
            >
              <code
                style={{
                  fontFamily: 'var(--font-family-code)',
                  fontSize: 13,
                  fontWeight: 600,
                  color: 'var(--color-text-heading)',
                  width: 64,
                }}
              >
                {v.version}
              </code>
              {v.status === 'active' ? <Tag color="green">서빙 중</Tag> : <Tag>이전 배포</Tag>}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: 13,
                    color: 'var(--color-text)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
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
    </Drawer>
  )
}

/* ---- External A2A agent detail (read-only; meta owned by the remote A2A card, 026) ---- */
function ExternalAgentDetail({
  agent,
  onClose,
  onDelete,
}: {
  agent: Agent
  onClose: () => void
  onDelete: (a: Agent) => void
}) {
  const card = agent.card
  const caps = Object.entries(card?.capabilities ?? {})
    .filter(([, v]) => v === true)
    .map(([k]) => k)
  return (
    <Drawer
      open={!!agent}
      title={agent.name}
      width={480}
      onClose={onClose}
      footer={
        <Button danger icon={<Icon name="delete" />} onClick={() => onDelete(agent)}>
          등록 해제
        </Button>
      }
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <Avatar size="large" style={{ background: 'var(--purple-1)', color: 'var(--purple-7)' }}>
          <Icon name="robot" />
        </Avatar>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
            {agent.name}
            <Tag color="purple">
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <Icon name="robot" size={11} />
                외부 A2A
              </span>
            </Tag>
            {card?.version ? <Tag>v{card.version}</Tag> : null}
          </div>
          <code style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>
            {agent.agentId}
          </code>
        </div>
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 14 }}
        message="A2A 카드로 등록한 외부 에이전트입니다. 구성은 원격 서비스가 소유하므로 콘솔에서는 읽기 전용입니다. 실제 호출은 준비 중(런타임은 2차 스펙) — 지금은 카드 확인까지 지원합니다."
      />

      {card?.description ? (
        <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginBottom: 14 }}>{card.description}</div>
      ) : null}

      <div
        style={{
          padding: 14,
          border: '1px solid var(--purple-3)',
          background: 'var(--purple-1)',
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
          <Icon name="global" size={12} style={{ color: 'var(--purple-7)' }} />
          A2A 카드
        </div>
        <IdRow label="Endpoint" value={card?.url || agent.endpoint || '—'} />
        <Desc label="제공자" width={84}>
          {card?.provider?.organization || '—'}
        </Desc>
        {caps.length ? (
          <Desc label="기능" width={84}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {caps.map((c) => (
                <Tag key={c} color="blue">{c}</Tag>
              ))}
            </div>
          </Desc>
        ) : null}
        <Desc label="등록일" width={84}>
          {agent.registeredAt || '—'}
        </Desc>
      </div>

      {card?.skills?.length ? (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)', marginBottom: 10 }}>
            스킬 (skills)
          </div>
          <div
            style={{
              border: '1px solid var(--color-border-secondary)',
              borderRadius: 'var(--radius-lg)',
              overflow: 'hidden',
            }}
          >
            {card.skills.map((s, i) => (
              <div
                key={s.id ?? i}
                style={{
                  padding: '10px 14px',
                  borderTop: i ? '1px solid var(--color-border-secondary)' : 'none',
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text)' }}>{s.name ?? s.id}</div>
                {s.description ? (
                  <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{s.description}</div>
                ) : null}
                {s.tags?.length ? (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                    {s.tags.map((t) => (
                      <Tag key={t} color="cyan">{t}</Tag>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Drawer>
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
  onResync,
  onNewDraft,
}: {
  agent: Agent | null
  onClose: () => void
  onEdit: (a: Agent) => void
  onDelete: (a: Agent) => void
  onToggleExpose: (a: Agent) => void
  onActivate: (a: Agent, v: VersionMeta) => void
  onTest: (a: Agent, v: VersionMeta) => void
  onRevert: (a: Agent, v: VersionMeta) => void
  onResync: (a: Agent) => void
  onNewDraft: (a: Agent) => void
}) {
  if (!agent) return null
  if (agent.source === 'code')
    return (
      <CodeAgentDetail
        agent={agent}
        onClose={onClose}
        onDelete={onDelete}
        onResync={onResync}
      />
    )
  if (agent.source === 'external')
    return (
      <ExternalAgentDetail
        agent={agent}
        onClose={onClose}
        onDelete={onDelete}
      />
    )
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
          description="지정한 커스텀 런타임(impl)이 신뢰 레지스트리에서 미해결입니다(미등록 또는 공통 인터페이스 부적합). 기본 에이전트로 만회·폴백하지 않습니다(스펙 089). 구현을 등록·수정하거나 impl 설정을 비우세요."
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
      {(agent.memories || []).includes('장기 기억 (mem0)') ? (
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
      {(agent.memories || []).includes('장기 기억 (mem0)') && agent.source === 'ui' ? (
        <Desc label="에이전트 지식 (mem0)">
          <AgentMemoryPanel agentId={agent.id} />
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
          <IdRow label="A2A 카드" value={a2aCardUrl(agent.id)} />
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', margin: '2px 0 0 84px' }}>
            이 URL을 <strong>“원격 에이전트 연결”</strong>에 그대로 붙여 등록·테스트하세요. 루프백/사설
            주소면 백엔드에 <code style={{ fontFamily: 'var(--font-family-code)' }}>A2A_ALLOWED_HOSTS=127.0.0.1</code>가 필요합니다.
          </div>
        </div>
      ) : null}

      <div style={{ marginTop: 18 }}>
        <VersionHistory
          versions={agent.versions || []}
          onActivate={(v) => onActivate(agent, v)}
          onTest={(v) => onTest(agent, v)}
          onRevert={(v) => onRevert(agent, v)}
          onNewDraft={draft ? null : () => onNewDraft(agent)}
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
  const [agents, setAgents] = useState<Agent[]>([])
  const [blocks, setBlocks] = useState<Record<string, BlockCategory>>({})
  const [models, setModels] = useState<Model[]>([])
  const [collections, setCollections] = useState<Collection[]>([])
  const [detailId, setDetailId] = useState<string | null>(null)
  const detail = agents.find((a) => a.id === detailId) || null
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<{ agent: Agent; version: string | null } | null>(null)
  const [confirmDel, setConfirmDel] = useState<Agent | null>(null)
  const [exposeOff, setExposeOff] = useState<{ agent: Agent; count: number } | null>(null) // agent pending expose-off confirm
  const [connectOpen, setConnectOpen] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 2400)
    return () => clearTimeout(t)
  }, [toast])

  // 마운트 시 백엔드에서 에이전트 목록 + 빌딩 블록을 로드.
  useEffect(() => {
    listAgents()
      .then(setAgents)
      .catch((e) => message.error(String(e)))
    getBlocks()
      .then(setBlocks)
      .catch((e) => message.error(String(e)))
    listModels('chat')
      .then(setModels)
      .catch((e) => message.error(String(e)))
    // RAG 컬렉션(지식 소스 피커용, 스펙 037). 비어 있어도 폼은 안내 문구를 띄운다.
    listCollections()
      .then(setCollections)
      .catch((e) => message.error(String(e)))
  }, [])

  // 단일 에이전트를 반환값(전체 AgentOut)으로 교체. 활성화·편집·되돌리기·새초안·재동기 등
  // 단일 변경의 공통 종점 — 여기서 탭 간 변경 신호를 쏜다(스펙 080). 초기 로드는 setAgents 직접
  // 사용이라 신호가 안 나가 불필요한 재페치를 안 만든다.
  const replaceAgent = (updated: Agent) => {
    setAgents((as) => as.map((a) => (a.id === updated.id ? updated : a)))
    notifyAgentsChanged()
  }

  const configOf = (a: Agent): AgentConfig => ({
    model: a.model,
    persona: a.persona,
    temperature: a.temperature ?? null,
    memories: [...(a.memories || [])],
    historyDepth: a.historyDepth,
    persistHistory: a.persistHistory ?? true,
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
  // 라이브 세션 카운트는 더 이상 추적하지 않는다(ADMIN_SESSIONS 제거). UX용 모달만 유지.
  const toggleExpose = async (agent: Agent) => {
    // A2A 노출은 로컬(ui) 에이전트만 — 스펙 083 불변식. 렌더 단계서 토글을 이미 숨기지만,
    // 헬퍼가 재사용돼도 켜는 호출이 새지 않도록 중앙에서도 source 가드(끄기는 멱등 청소라 허용).
    if (!agent.exposed.a2a && agent.source !== 'ui') {
      message.warning('원격/외부 에이전트는 A2A로 노출할 수 없습니다')
      return
    }
    if (!agent.exposed.a2a) {
      try {
        const updated = await exposeAgent(agent.id, true)
        replaceAgent(updated)
        setToast(`${agent.name} — A2A 공개됨`)
      } catch (e) {
        message.error(String(e))
      }
      return
    }
    // turning OFF — 확인 모달을 띄운다(액션은 모두 exposeAgent(false)).
    setExposeOff({ agent, count: 0 })
  }
  const exposeOffApply = async (mode: 'drain' | 'revoke') => {
    if (!exposeOff) return
    const { agent } = exposeOff
    try {
      const updated = await exposeAgent(agent.id, false)
      replaceAgent(updated)
      setToast(mode === 'drain' ? `${agent.name} 사용 중단 — A2A 비공개로 전환` : `${agent.name} — A2A 철회됨`)
    } catch (e) {
      message.error(String(e))
    }
    setExposeOff(null)
  }
  const deprecate = () => exposeOffApply('drain')
  const revokeNow = () => exposeOffApply('revoke')
  const activateVersion = async (agent: Agent, v: VersionMeta) => {
    try {
      const updated = await apiActivateVersion(agent.id, v.version)
      replaceAgent(updated)
      setToast(`${agent.name} ${v.version} 활성화됨 — 서빙 시작`)
    } catch (e) {
      message.error(String(e))
    }
  }
  const newDraft = async (agent: Agent) => {
    try {
      const updated = await apiForkVersion(agent.id)
      replaceAgent(updated)
      setToast(`${agent.name} 새 초안 생성됨`)
    } catch {
      // 400: 이미 초안이 있음 등 — 서버 가드.
      message.warning('새 초안을 만들 수 없습니다 — 이미 초안이 있는지 확인하세요')
    }
  }
  const testVersion = (agent: Agent, v: VersionMeta) =>
    setToast(`${agent.name} ${v.version}(초안 구성) 테스트 — 디버그 콘솔을 열세요`)
  const revertToDraft = async (agent: Agent, v: VersionMeta) => {
    try {
      const updated = await apiRevertVersion(agent.id, v.version)
      replaceAgent(updated)
      setToast(`${v.version} 초안으로 되돌림${v.status === 'active' ? ' — 이전 버전으로 롤백' : ''}`)
    } catch {
      // 서버가 가드를 강제(400 + 한국어 detail). api.ts 에러는 status만 담으므로 일반 메시지로 안내.
      message.warning('되돌릴 수 없습니다 — 조건을 확인하세요')
    }
  }

  const save = async (data: AgentFormData) => {
    const config: AgentConfig = {
      model: data.model,
      persona: data.persona,
      temperature: data.temperature,
      memories: data.memories,
      historyDepth: data.historyDepth,
      persistHistory: data.persistHistory,
      vectorTables: data.vectorTables,
      permissions: data.permissions,
      mcps: data.mcps,
    }
    try {
      if (editing) {
        const updated = await updateAgent(editing.agent.id, data.name, config)
        replaceAgent(updated)
        setToast(`초안에 저장됨 — 활성화하면 게시됩니다`)
      } else {
        const created = await createAgent(data.name, config)
        setAgents((as) => [created, ...as])
        notifyAgentsChanged()
        setToast(`"${data.name}" 생성됨 — v1 초안, 테스트 후 활성화`)
      }
      setFormOpen(false)
      setEditing(null)
    } catch (e) {
      message.error(String(e))
    }
  }

  const doDelete = async () => {
    if (!confirmDel) return
    const target = confirmDel
    try {
      await deleteAgent(target.id)
      setAgents((as) => as.filter((a) => a.id !== target.id))
      notifyAgentsChanged()
      setToast(`"${target.name}" ${target.source !== 'ui' ? '등록 해제됨' : '삭제됨'}`)
      setConfirmDel(null)
      setDetailId(null)
    } catch (e) {
      message.error(String(e))
    }
  }

  // ---- 원격 에이전트 연결(스펙 057): URL 하나로 백엔드가 카드 fetch·검증·provenance 자동분류 ----
  // 프론트는 매니페스트를 날조하지 않는다 — 토큰 마스킹·분류는 모두 서버. 반환 source로 토스트를 도출.
  const connectAgent = async (data: { url: string; token: string }) => {
    try {
      const created = await apiConnectAgent(data.url, data.token || undefined)
      setAgents((as) => [created, ...as])
      notifyAgentsChanged()
      const kind = created.source === 'code' ? 'SDK 에이전트 (코드)' : '외부 A2A'
      setToast(`"${created.name || '원격 에이전트'}" 연결됨 — ${kind}, 읽기 전용`)
      setConnectOpen(false)
    } catch (e) {
      message.error(`연결 실패 — ${String(e)}`)
    }
  }
  const resync = async (agent: Agent) => {
    try {
      const updated = await resyncAgent(agent.id)
      replaceAgent(updated)
      setToast(`${agent.name} 재동기화됨 — 최신 배포(commit) 반영`)
    } catch (e) {
      message.error(String(e))
    }
  }

  const columns: Column<Agent>[] = [
    {
      key: 'name',
      title: '에이전트',
      render: (a) => {
        const isCode = a.source === 'code'
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Avatar
              size="small"
              style={{
                background: isCode ? 'var(--geekblue-1)' : 'var(--gray-12)',
                color: isCode ? 'var(--geekblue-7)' : '#fff',
              }}
            >
              <Icon name={isCode ? 'code' : 'robot'} size={14} />
            </Avatar>
            <div>
              <div style={{ fontWeight: 500, color: 'var(--color-text-heading)' }}>{a.name}</div>
              <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>
                {a.model}
              </div>
            </div>
          </div>
        )
      },
    },
    {
      key: 'source',
      title: '소스',
      width: 104,
      hideBelow: 'xl',
      render: (a) => {
        const s = AGENT_SOURCE[a.source || 'ui'] || AGENT_SOURCE.ui
        return (
          <Tag color={s.tag === 'default' ? undefined : s.tag}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              {s.icon ? <Icon name={s.icon} size={11} /> : null}
              {s.label}
            </span>
          </Tag>
        )
      },
    },
    {
      key: 'conformance',
      title: '준수',
      width: 96,
      render: (a) => {
        const c = AGENT_CONFORMANCE[a.conformance || 'conforming'] || AGENT_CONFORMANCE.conforming
        const isError = a.conformance === 'config_error'
        return (
          <Tooltip title={c.desc}>
            <Tag color={c.tag === 'default' ? undefined : c.tag}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontWeight: isError ? 600 : 400 }}>
                {c.icon ? <Icon name={c.icon} size={11} /> : null}
                {c.label}
              </span>
            </Tag>
          </Tooltip>
        )
      },
    },
    {
      key: 'persona',
      title: '페르소나',
      render: (a) => <span style={{ color: 'var(--color-text-secondary)' }}>{a.persona}</span>,
    },
    {
      key: 'mcps',
      title: 'MCP',
      hideBelow: 'xxl',
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
      hideBelow: 'xxl',
      render: (a) => {
        if (a.source === 'code')
          return (
            <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, color: 'var(--color-text-heading)' }}>
              {a.commit || a.activeVersion}
            </code>
          )
        if (a.source === 'external')
          return (
            <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, color: 'var(--color-text-heading)' }}>
              {a.card?.version ? 'v' + a.card.version : '—'}
            </code>
          )
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
      hideBelow: 'xl',
      render: (a) =>
        // A2A 노출은 로컬(ui) 에이전트만 — 원격(code)·외부(external)는 이미 원격 A2A/프록시라 재노출 불가(스펙 083).
        a.source !== 'ui' ? (
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>—</span>
        ) : (
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
          {a.source === 'code' || a.source === 'external' ? (
            <Button
              type="text"
              size="small"
              icon={<Icon name="lock" />}
              disabled
              title={a.source === 'external' ? '외부 A2A 카드로 관리됨 — 편집 잠금' : '코드에서 관리됨 — 편집 잠금'}
            />
          ) : (
            <Button type="text" size="small" icon={<Icon name="edit" />} onClick={() => openEdit(a)} />
          )}
          <Button type="text" size="small" danger icon={<Icon name="delete" />} onClick={() => setConfirmDel(a)} />
        </span>
      ),
    },
  ]

  return (
    <Page
      title="에이전트"
      subtitle={`빌딩 블록으로 구성하거나 코드로 배포한 에이전트 ${agents.length}개`}
      actions={
        <span style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          <Button icon={<Icon name="link" />} onClick={() => setConnectOpen(true)}>
            원격 에이전트 연결
          </Button>
          <Button type="primary" icon={<Icon name="plus" />} onClick={openCreate}>
            새 에이전트
          </Button>
        </span>
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
        onResync={resync}
        onNewDraft={newDraft}
      />
      <ConnectAgentModal open={connectOpen} onCancel={() => setConnectOpen(false)} onConnect={connectAgent} />
      <AgentForm
        open={formOpen}
        mode={editing ? 'edit' : 'create'}
        blocks={blocks}
        models={models}
        collections={collections}
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
                  temperature: c.temperature ?? a.temperature ?? null,
                  memories: [...(c.memories || [])],
                  historyDepth: c.historyDepth != null ? c.historyDepth : a.historyDepth,
                  persistHistory: c.persistHistory ?? a.persistHistory ?? true,
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
        title={confirmDel && confirmDel.source !== 'ui' ? '에이전트 등록을 해제할까요?' : '에이전트를 삭제할까요?'}
        okText={confirmDel && confirmDel.source !== 'ui' ? '등록 해제' : '삭제'}
        cancelText="취소"
        onCancel={() => setConfirmDel(null)}
        onOk={doDelete}
      >
        {confirmDel ? (
          confirmDel.source === 'code' ? (
            <div>
              <b>{confirmDel.name}</b>를 콘솔에서 등록 해제합니다. 배포된 코드는 그대로 실행되지만, 이 콘솔에서의
              연결·모니터링과 A2A 공개가 제거됩니다.
            </div>
          ) : confirmDel.source === 'external' ? (
            <div>
              <b>{confirmDel.name}</b>를 콘솔에서 등록 해제합니다. 외부 A2A 서비스는 그대로지만, 이 콘솔에서의
              카드 등록·모니터링과 A2A 공개가 제거됩니다.
            </div>
          ) : (
            <div>
              <b>{confirmDel.name}</b> 및 공개 엔드포인트가 영구 삭제됩니다. 진행 중인 세션도 종료됩니다. 되돌릴 수
              없습니다.
            </div>
          )
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
              <b>{exposeOff.agent.name}</b>의 A2A 공개를 끕니다. 오프라인 방식을 선택하세요:
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
              <div style={{ display: 'flex', gap: 8 }}>
                <Icon name="pause-circle" size={15} style={{ color: 'var(--volcano-6)', marginTop: 2, flex: 'none' }} />
                <span>
                  <b>사용 중단(드레인)</b> — 신규 세션을 막고 진행 중인 세션을 끝낸 뒤 비공개로 전환. 소비자에게 가장
                  안전.
                </span>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Icon name="close-circle" size={15} style={{ color: 'var(--color-error)', marginTop: 2, flex: 'none' }} />
                <span>
                  <b>즉시 철회</b> — 엔드포인트를 즉시 차단; 진행 중인 세션이 종료되고 외부 호출자는 오류를 받습니다.
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
