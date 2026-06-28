/* my-agents admin — 프로바이더·모델 통합 뷰 (스펙 047 #6·#7·#8).
   ProvidersView + ModelsView를 하나의 마스터-디테일로 합친다.
   - 마스터(좌): 프로바이더 목록 + kind 배지/설명/모델수, [+ 프로바이더].
   - 디테일(우): 선택 프로바이더의 GET /models 실모델 나열 + 체크박스 토글(등록/해제),
     models.dev 카탈로그 메타(ctx·modalities·cost) 칩. 도달 실패 시 안내 배너. 직접 추가 폼.
   토글 ON = 모델 등록 모달(POST /models, meta 포함), OFF = DELETE /models/{id}(에이전트 참조 시 409). */
import { useState, useEffect } from 'react'
import { Tag, Button, Modal, Input, Select, Switch, Checkbox, Tooltip, message } from 'antd'
import { Page, Panel } from '../shared'
import { Icon } from '../icons'
import {
  listProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  testProviderConfig,
  testSavedProvider,
  listAvailableModels,
  createModel,
  deleteModel,
  testModelConfig,
  type Provider,
  type ProviderKind,
  type AvailableModel,
  type AvailableModelsOut,
  type CatalogMeta,
  type ModelProbeResult,
} from '../../api'

const codeStyle = { fontFamily: 'var(--font-family-code)', fontSize: 12 }

/* kind 배지: 색 + 라벨 + 한 줄 힌트(#6 라벨 혼란 해소). */
const KIND: Record<ProviderKind, { color: string; label: string; hint: string }> = {
  local: { color: 'green', label: 'Local', hint: '내 머신에서 실행되는 모델' },
  mock: { color: 'gold', label: 'Mock', hint: '라이브 없이 결정적 응답을 주는 내장 목' },
  remote: { color: 'geekblue', label: 'Remote', hint: '외부 API 엔드포인트' },
}
const KIND_OPTS = (Object.keys(KIND) as ProviderKind[]).map((k) => ({
  label: `${KIND[k].label} — ${KIND[k].hint}`,
  value: k,
}))

function KindBadge({ kind }: { kind: ProviderKind }) {
  const m = KIND[kind] ?? KIND.remote
  return (
    <Tooltip title={m.hint}>
      <Tag color={m.color} style={{ marginInlineEnd: 0 }}>
        {m.label}
      </Tag>
    </Tooltip>
  )
}

/* 카탈로그 메타 → 사람이 읽는 칩 텍스트. 숫자는 K/M 축약. */
const fmtNum = (n?: number | null): string | null => {
  if (n == null) return null
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`
  if (n >= 1000) return `${+(n / 1000).toFixed(0)}K`
  return String(n)
}
function CatalogChips({ c }: { c: CatalogMeta | null }) {
  if (!c) {
    return <span style={{ fontSize: 12, color: 'var(--color-text-quaternary)' }}>카탈로그 미수록</span>
  }
  const chips: string[] = []
  const ctx = fmtNum(c.context)
  if (ctx) chips.push(`${ctx} ctx`)
  const inp = c.modalities?.input?.join('+')
  const out = c.modalities?.output?.join('+')
  if (inp || out) chips.push(`${inp || '?'}→${out || '?'}`)
  if (c.cost?.input != null || c.cost?.output != null)
    chips.push(`$${c.cost?.input ?? '?'}/$${c.cost?.output ?? '?'} per Mtok`)
  const caps = c.capabilities || {}
  const capNames = [
    caps.reasoning && 'reasoning',
    caps.tool_call && 'tools',
    caps.structured_output && 'structured',
    caps.attachment && 'vision',
  ].filter(Boolean) as string[]
  return (
    <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
      {chips.map((t) => (
        <Tag key={t} style={{ fontSize: 11, marginInlineEnd: 0 }}>
          {t}
        </Tag>
      ))}
      {capNames.map((t) => (
        <Tag key={t} color="purple" style={{ fontSize: 11, marginInlineEnd: 0 }}>
          {t}
        </Tag>
      ))}
    </span>
  )
}

/* ── 프로바이더 등록/수정 모달 (kind·description 포함) ───────────────────────── */
interface ProviderForm {
  name: string
  kind: ProviderKind
  description: string
  protocol: string
  base_url: string
  api_key: string
}
const blankProvider: ProviderForm = {
  name: '',
  kind: 'remote',
  description: '',
  protocol: 'openai-compatible',
  base_url: '',
  api_key: '',
}

function ProviderModal({
  open,
  editing,
  onCancel,
  onSubmit,
}: {
  open: boolean
  editing: Provider | null
  onCancel: () => void
  onSubmit: (data: ProviderForm) => void
}) {
  const [f, setF] = useState<ProviderForm>(blankProvider)
  const [testing, setTesting] = useState(false)
  const [probe, setProbe] = useState<ModelProbeResult | null>(null)

  useEffect(() => {
    if (open) {
      setF(
        editing
          ? {
              name: editing.name,
              kind: editing.kind,
              description: editing.description,
              protocol: editing.protocol,
              base_url: editing.base_url,
              api_key: editing.api_key ?? '',
            }
          : blankProvider,
      )
      setProbe(null)
    }
  }, [open, editing])

  const set = <K extends keyof ProviderForm>(k: K, v: ProviderForm[K]) => {
    setProbe(null)
    setF((s) => ({ ...s, [k]: v }))
  }

  const runTest = async () => {
    setTesting(true)
    setProbe(null)
    try {
      setProbe(await testProviderConfig({ base_url: f.base_url, api_key: f.api_key }))
    } catch (e) {
      setProbe({
        ok: false, reachable: false, modelAvailable: false, latencyMs: 0,
        detail: e instanceof Error ? e.message : '연결 테스트에 실패했습니다',
      })
    } finally {
      setTesting(false)
    }
  }

  return (
    <Modal
      open={open}
      width={520}
      title={editing ? '프로바이더 수정' : '프로바이더 등록'}
      okText={editing ? '저장' : '등록'}
      cancelText="취소"
      onCancel={onCancel}
      onOk={() => onSubmit(f)}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '60vh', overflow: 'auto' }}>
        <Field label="이름">
          <Input placeholder="예: OpenAI (프로덕션)" value={f.name} onChange={(e) => set('name', e.target.value)} />
        </Field>
        <Field label="종류">
          <Select value={f.kind} onChange={(v) => set('kind', v)} style={{ width: '100%' }} options={KIND_OPTS} />
        </Field>
        <Field label="설명">
          <Input
            placeholder="한 줄 설명 (예: 실제 로컬 MLX 서버)"
            value={f.description}
            onChange={(e) => set('description', e.target.value)}
          />
        </Field>
        <Field label="프로토콜">
          <Input placeholder="openai-compatible" value={f.protocol} onChange={(e) => set('protocol', e.target.value)} />
        </Field>
        <Field label="Base URL">
          <Input
            prefix={<Icon name="global" />}
            placeholder="http://localhost:8045/v1"
            value={f.base_url}
            onChange={(e) => set('base_url', e.target.value)}
          />
        </Field>
        <Field label="API 키">
          <Input.Password
            prefix={<Icon name="key" />}
            placeholder={editing ? '변경하지 않으려면 그대로 두세요' : ''}
            value={f.api_key}
            onChange={(e) => set('api_key', e.target.value)}
          />
          {editing ? (
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              마스킹 값(•) 그대로면 기존 키 유지 · 비우면 키 제거 · 새 값이면 교체
            </span>
          ) : null}
        </Field>
        <ProbeRow testing={testing} disabled={testing || !f.base_url.trim()} probe={probe} onTest={runTest} />
      </div>
    </Modal>
  )
}

/* ── 모델 등록 모달 (프로바이더 고정; 토글 ON·직접추가 공용) ─────────────────── */
interface ModelForm {
  name: string
  kind: 'chat' | 'embedding'
  model_id: string
  is_default: boolean
}

function ModelModal({
  open,
  provider,
  prefill,
  onCancel,
  onCreate,
}: {
  open: boolean
  provider: Provider | null
  prefill: { model_id?: string; meta?: Record<string, unknown> } | null
  onCancel: () => void
  onCreate: (data: ModelForm, meta: Record<string, unknown>) => void
}) {
  const [f, setF] = useState<ModelForm>({ name: '', kind: 'chat', model_id: '', is_default: false })
  const [testing, setTesting] = useState(false)
  const [probe, setProbe] = useState<ModelProbeResult | null>(null)

  useEffect(() => {
    if (open) {
      const mid = prefill?.model_id ?? ''
      // 토글 ON은 raw id를 그대로 표시 이름의 기본값으로 — 사용자가 다듬을 수 있게.
      setF({ name: mid, kind: 'chat', model_id: mid, is_default: false })
      setProbe(null)
    }
  }, [open, prefill])

  const set = <K extends keyof ModelForm>(k: K, v: ModelForm[K]) => {
    setProbe(null)
    setF((s) => ({ ...s, [k]: v }))
  }

  const runTest = async () => {
    if (!provider) return
    setTesting(true)
    setProbe(null)
    try {
      setProbe(await testModelConfig({ provider_id: provider.id, model_id: f.model_id, kind: f.kind }))
    } catch (e) {
      setProbe({
        ok: false, reachable: false, modelAvailable: false, latencyMs: 0,
        detail: e instanceof Error ? e.message : '연결 테스트에 실패했습니다',
      })
    } finally {
      setTesting(false)
    }
  }

  return (
    <Modal
      open={open}
      width={520}
      title={`모델 등록 — ${provider?.name ?? ''}`}
      okText="등록"
      cancelText="취소"
      onCancel={onCancel}
      onOk={() => onCreate(f, prefill?.meta ?? {})}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '60vh', overflow: 'auto' }}>
        <Field label="이름">
          <Input placeholder="예: gpt-4o (프로덕션)" value={f.name} onChange={(e) => set('name', e.target.value)} />
        </Field>
        <Field label="종류">
          <Select
            value={f.kind}
            onChange={(v) => set('kind', v)}
            style={{ width: '100%' }}
            options={[
              { label: 'Chat', value: 'chat' },
              { label: 'Embedding', value: 'embedding' },
            ]}
          />
        </Field>
        <Field label="모델 ID">
          <Input placeholder="mlx-community/..." value={f.model_id} onChange={(e) => set('model_id', e.target.value)} />
        </Field>
        <label style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Switch checked={f.is_default} onChange={(v) => set('is_default', v)} />
          <span style={{ fontSize: 14, fontWeight: 500 }}>기본 모델</span>
        </label>
        <ProbeRow
          testing={testing}
          disabled={testing || !provider || !f.model_id.trim()}
          probe={probe}
          onTest={runTest}
        />
      </div>
    </Modal>
  )
}

/* 작은 공용 조각들 */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontSize: 14, fontWeight: 500 }}>{label}</span>
      {children}
    </label>
  )
}
function ProbeRow({
  testing,
  disabled,
  probe,
  onTest,
}: {
  testing: boolean
  disabled: boolean
  probe: ModelProbeResult | null
  onTest: () => void
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <Button
        icon={<Icon name="thunderbolt" />}
        loading={testing}
        disabled={disabled}
        onClick={onTest}
        style={{ alignSelf: 'flex-start' }}
      >
        연결 테스트
      </Button>
      {probe ? (
        <div
          style={{
            padding: '8px 12px',
            borderRadius: 6,
            fontSize: 13,
            border: `1px solid ${probe.ok ? 'var(--color-success-border)' : 'var(--color-error-border)'}`,
            background: probe.ok ? 'var(--color-success-bg)' : 'var(--color-error-bg)',
            color: probe.ok ? 'var(--color-success)' : 'var(--color-error)',
          }}
        >
          {probe.ok ? `✓ ${probe.detail} (${probe.latencyMs}ms)` : `✗ ${probe.detail}`}
        </div>
      ) : null}
    </div>
  )
}

/* ── 메인 뷰 ─────────────────────────────────────────────────────────────────── */
export default function ProviderModelView() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [avail, setAvail] = useState<AvailableModelsOut | null>(null)
  const [availLoading, setAvailLoading] = useState(false)
  const [busyMid, setBusyMid] = useState<string | null>(null) // 토글 진행 중 model_id

  const [provModal, setProvModal] = useState<{ editing: Provider | null } | null>(null)
  const [modelModal, setModelModal] = useState<{ prefill: { model_id?: string; meta?: Record<string, unknown> } | null } | null>(null)
  const [confirmProvDel, setConfirmProvDel] = useState<Provider | null>(null)
  const [confirmModelDel, setConfirmModelDel] = useState<AvailableModel | null>(null)
  const [testingProv, setTestingProv] = useState(false)

  const selected = providers.find((p) => p.id === selectedId) ?? null

  const loadProviders = async (keepSel = true) => {
    try {
      const ps = await listProviders()
      setProviders(ps)
      if (!keepSel || !ps.some((p) => p.id === selectedId)) {
        setSelectedId(ps[0]?.id ?? null)
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : '프로바이더를 불러오지 못했습니다')
    }
  }

  useEffect(() => {
    void loadProviders(false)
    /* eslint-disable-next-line */
  }, [])

  // 선택이 바뀌면 그 프로바이더의 실모델을 자동 조회.
  const loadAvail = async (id: string) => {
    setAvailLoading(true)
    setAvail(null)
    try {
      setAvail(await listAvailableModels(id))
    } catch (e) {
      message.error(e instanceof Error ? e.message : '모델 목록을 불러오지 못했습니다')
    } finally {
      setAvailLoading(false)
    }
  }
  useEffect(() => {
    if (selectedId) void loadAvail(selectedId)
    else setAvail(null)
    /* eslint-disable-next-line */
  }, [selectedId])

  const refresh = async () => {
    await loadProviders()
    if (selectedId) await loadAvail(selectedId)
  }

  const submitProvider = async (data: ProviderForm) => {
    if (!data.name.trim() || !data.base_url.trim()) {
      message.warning('이름과 Base URL을 입력하세요')
      return
    }
    const body = {
      name: data.name.trim(),
      kind: data.kind,
      description: data.description.trim(),
      protocol: data.protocol.trim() || 'openai-compatible',
      base_url: data.base_url.trim(),
      api_key: data.api_key,
    }
    try {
      if (provModal?.editing) await updateProvider(provModal.editing.id, body)
      else {
        const created = await createProvider(body)
        setSelectedId(created.id)
      }
      await loadProviders()
      setProvModal(null)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '저장에 실패했습니다')
    }
  }

  const deleteProviderRow = async () => {
    if (!confirmProvDel) return
    try {
      await deleteProvider(confirmProvDel.id)
      setConfirmProvDel(null)
      await loadProviders(false)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '삭제에 실패했습니다')
    }
  }

  const testProvider = async () => {
    if (!selected) return
    setTestingProv(true)
    try {
      const r = await testSavedProvider(selected.id)
      if (r.ok) message.success(r.detail)
      else message.warning(r.detail)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '연결 테스트에 실패했습니다')
    } finally {
      setTestingProv(false)
    }
  }

  // 체크박스 토글: 미등록→등록 모달, 등록됨→해제 확인.
  const onToggle = (m: AvailableModel) => {
    if (m.registered) setConfirmModelDel(m)
    else setModelModal({ prefill: { model_id: m.model_id, meta: (m.catalog as Record<string, unknown>) ?? {} } })
  }

  const createModelRow = async (data: ModelForm, meta: Record<string, unknown>) => {
    if (!selected) return
    if (!data.name.trim() || !data.model_id.trim()) {
      message.warning('이름과 모델 ID를 입력하세요')
      return
    }
    setBusyMid(data.model_id)
    try {
      await createModel({
        name: data.name.trim(),
        provider_id: selected.id,
        model_id: data.model_id.trim(),
        kind: data.kind,
        is_default: data.is_default,
        params: {},
        meta,
      })
      setModelModal(null)
      await refresh()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '모델 등록에 실패했습니다')
    } finally {
      setBusyMid(null)
    }
  }

  const deleteModelRow = async () => {
    if (!confirmModelDel?.registered_id) return
    setBusyMid(confirmModelDel.model_id)
    try {
      await deleteModel(confirmModelDel.registered_id)
      setConfirmModelDel(null)
      await refresh()
    } catch (e) {
      // 에이전트가 이름으로 참조 중이면 서버가 409 + 안내를 준다(learning 042).
      message.error(e instanceof Error ? e.message : '삭제에 실패했습니다')
    } finally {
      setBusyMid(null)
    }
  }

  return (
    <Page
      title="프로바이더·모델"
      subtitle="LLM 연결처와 그 실모델을 한 화면에서 관리 — 좌측 프로바이더 선택 → 우측에서 모델 토글"
      actions={
        <Button type="primary" icon={<Icon name="plus" />} onClick={() => setProvModal({ editing: null })}>
          프로바이더 등록
        </Button>
      }
    >
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        {/* 마스터 — 프로바이더 목록 */}
        <Panel style={{ flex: '1 1 320px', minWidth: 280, maxWidth: 420 }}>
          {providers.length === 0 ? (
            <div style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--color-text-tertiary)' }}>
              등록된 프로바이더가 없습니다
            </div>
          ) : (
            providers.map((p) => {
              const sel = p.id === selectedId
              return (
                <div
                  key={p.id}
                  onClick={() => setSelectedId(p.id)}
                  style={{
                    padding: '12px 16px',
                    cursor: 'pointer',
                    borderLeft: `3px solid ${sel ? 'var(--color-primary)' : 'transparent'}`,
                    background: sel ? 'var(--color-primary-bg)' : 'transparent',
                    borderBottom: '1px solid var(--color-border-secondary)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 500, color: 'var(--color-text-heading)', flex: 1, minWidth: 0 }}>
                      {p.name}
                    </span>
                    <KindBadge kind={p.kind} />
                    {p.modelCount > 0 ? (
                      <Tag color="blue" style={{ marginInlineEnd: 0 }}>
                        {p.modelCount}
                      </Tag>
                    ) : null}
                  </div>
                  {p.description ? (
                    <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 4 }}>
                      {p.description}
                    </div>
                  ) : null}
                  <code style={{ ...codeStyle, color: 'var(--color-text-quaternary)', display: 'block', marginTop: 4 }}>
                    {p.base_url}
                  </code>
                </div>
              )
            })
          )}
        </Panel>

        {/* 디테일 — 선택 프로바이더의 실모델 */}
        <Panel style={{ flex: '2 1 440px', minWidth: 320, padding: 20 }}>
          {!selected ? (
            <div style={{ color: 'var(--color-text-tertiary)' }}>프로바이더를 선택하세요</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* 헤더: 이름 + 배지 + 액션 */}
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <h3 style={{ fontSize: 18, margin: 0 }}>{selected.name}</h3>
                    <KindBadge kind={selected.kind} />
                  </div>
                  {selected.description ? (
                    <div style={{ fontSize: 13, color: 'var(--color-text-tertiary)', marginTop: 4 }}>
                      {selected.description}
                    </div>
                  ) : null}
                  <code style={{ ...codeStyle, color: 'var(--color-text-tertiary)', display: 'block', marginTop: 6 }}>
                    {selected.base_url}
                  </code>
                </div>
                <span style={{ display: 'inline-flex', gap: 4 }}>
                  <Button
                    size="small"
                    icon={<Icon name="thunderbolt" />}
                    loading={testingProv}
                    onClick={testProvider}
                  >
                    테스트
                  </Button>
                  <Button size="small" icon={<Icon name="edit" />} onClick={() => setProvModal({ editing: selected })} />
                  <Button size="small" danger icon={<Icon name="delete" />} onClick={() => setConfirmProvDel(selected)} />
                </span>
              </div>

              {/* 모델 툴바 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontWeight: 600, fontSize: 14 }}>모델</span>
                <Button size="small" icon={<Icon name="reload" />} loading={availLoading} onClick={() => loadAvail(selected.id)}>
                  GET /models
                </Button>
                <div style={{ flex: 1 }} />
                <Button size="small" type="dashed" icon={<Icon name="plus" />} onClick={() => setModelModal({ prefill: null })}>
                  직접 추가
                </Button>
              </div>

              {/* 도달 실패 배너 */}
              {avail && !avail.reachable ? (
                <div
                  style={{
                    padding: '8px 12px', borderRadius: 6, fontSize: 13,
                    border: '1px solid var(--color-warning-border)',
                    background: 'var(--color-warning-bg)', color: 'var(--color-warning)',
                  }}
                >
                  <Icon name="warning" /> 실모델 목록을 가져오지 못했습니다 — {avail.detail}. 등록된 모델만 표시합니다.
                </div>
              ) : null}

              {/* 모델 목록 */}
              {availLoading ? (
                <div style={{ color: 'var(--color-text-tertiary)' }}>불러오는 중…</div>
              ) : avail && avail.models.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {avail.models.map((m) => (
                    <div
                      key={m.model_id + (m.registered_id ?? '')}
                      style={{
                        display: 'flex', alignItems: 'flex-start', gap: 12, padding: '10px 12px',
                        border: '1px solid var(--color-border-secondary)', borderRadius: 8,
                        background: m.registered ? 'var(--color-success-bg)' : 'transparent',
                      }}
                    >
                      <Checkbox
                        checked={m.registered}
                        disabled={busyMid === m.model_id}
                        onChange={() => onToggle(m)}
                        style={{ marginTop: 2 }}
                      />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                          <code style={{ ...codeStyle, fontSize: 13, color: 'var(--color-text-heading)' }}>{m.model_id}</code>
                          {m.registered ? (
                            <Tag color="green" style={{ marginInlineEnd: 0 }}>
                              등록됨{m.registered_name && m.registered_name !== m.model_id ? ` · ${m.registered_name}` : ''}
                            </Tag>
                          ) : null}
                        </div>
                        <div style={{ marginTop: 6 }}>
                          <CatalogChips c={m.catalog} />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ color: 'var(--color-text-tertiary)', fontSize: 13 }}>
                  표시할 모델이 없습니다. [GET /models]로 실모델을 조회하거나 [직접 추가]로 등록하세요.
                </div>
              )}
            </div>
          )}
        </Panel>
      </div>

      <ProviderModal
        open={!!provModal}
        editing={provModal?.editing ?? null}
        onCancel={() => setProvModal(null)}
        onSubmit={submitProvider}
      />
      <ModelModal
        open={!!modelModal}
        provider={selected}
        prefill={modelModal?.prefill ?? null}
        onCancel={() => setModelModal(null)}
        onCreate={createModelRow}
      />

      <Modal
        open={!!confirmProvDel}
        title="프로바이더를 삭제할까요?"
        okText="삭제"
        cancelText="취소"
        onCancel={() => setConfirmProvDel(null)}
        onOk={deleteProviderRow}
      >
        {confirmProvDel ? (
          <div>
            <b>{confirmProvDel.name}</b>을(를) 삭제합니다.
            {confirmProvDel.modelCount > 0 ? (
              <div style={{ marginTop: 8, color: 'var(--color-error)' }}>
                매달린 모델 {confirmProvDel.modelCount}개가 있어 삭제가 차단됩니다. 먼저 모델을 제거하세요.
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={!!confirmModelDel}
        title="모델 등록을 해제할까요?"
        okText="해제"
        cancelText="취소"
        onCancel={() => setConfirmModelDel(null)}
        onOk={deleteModelRow}
      >
        {confirmModelDel ? (
          <div>
            <code style={codeStyle}>{confirmModelDel.model_id}</code> 등록을 해제(삭제)합니다. 이 모델을 이름으로
            참조하는 에이전트가 있으면 해제가 차단됩니다.
          </div>
        ) : null}
      </Modal>
    </Page>
  )
}
