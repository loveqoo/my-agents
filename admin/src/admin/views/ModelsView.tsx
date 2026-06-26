/* my-agents admin — Models view: LLM·임베딩 모델 레지스트리.
   목록 → 등록 모달. 에이전트 실행에 사용되는 chat/embedding 모델을 관리한다. */
import { useState, useEffect } from 'react'
import { Tag, Button, Modal, Input, Select, Switch, message } from 'antd'
import { Page, DataTable, type Column } from '../shared'
import { Icon } from '../icons'
import {
  listModels,
  listProviders,
  createModel,
  deleteModel,
  testModelConfig,
  testSavedModel,
  type Model,
  type Provider,
  type ModelProbeResult,
} from '../../api'

/* 등록 폼 데이터 shape. 연결처(base_url/api_key)는 provider에서 상속 → provider_id만 고른다. */
interface ModelFormData {
  name: string
  kind: 'chat' | 'embedding'
  provider_id: string
  model_id: string
  is_default: boolean
}

const blankForm: ModelFormData = {
  name: '',
  kind: 'chat',
  provider_id: '',
  model_id: '',
  is_default: false,
}

const codeStyle = { fontFamily: 'var(--font-family-code)', fontSize: 13 }

/* ---- 모델 등록 모달 ---- */
function RegisterModal({
  open,
  providers,
  onCancel,
  onCreate,
}: {
  open: boolean
  providers: Provider[]
  onCancel: () => void
  onCreate: (data: ModelFormData) => void
}) {
  const [f, setF] = useState<ModelFormData>(blankForm)
  const [testing, setTesting] = useState(false)
  const [probe, setProbe] = useState<ModelProbeResult | null>(null)

  useEffect(() => {
    if (open) {
      // provider가 하나면 기본 선택 — 입력 한 번 덜기.
      setF({ ...blankForm, provider_id: providers.length === 1 ? providers[0].id : '' })
      setProbe(null)
    }
  }, [open, providers])

  const set = <K extends keyof ModelFormData>(k: K, v: ModelFormData[K]) => {
    setProbe(null)
    setF((s) => ({ ...s, [k]: v }))
  }

  const runTest = async () => {
    setTesting(true)
    setProbe(null)
    try {
      const result = await testModelConfig({
        provider_id: f.provider_id,
        model_id: f.model_id,
        kind: f.kind,
      })
      setProbe(result)
    } catch (e) {
      setProbe({
        ok: false,
        reachable: false,
        modelAvailable: false,
        latencyMs: 0,
        detail: e instanceof Error ? e.message : '연결 테스트에 실패했습니다',
      })
    } finally {
      setTesting(false)
    }
  }

  const testDisabled = testing || !f.provider_id || !f.model_id.trim()

  return (
    <Modal
      open={open}
      width={520}
      title="모델 등록"
      okText="등록"
      cancelText="취소"
      onCancel={onCancel}
      onOk={() => onCreate(f)}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '60vh', overflow: 'auto' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>이름</span>
          <Input placeholder="예: gpt-4o (프로덕션)" value={f.name} onChange={(e) => set('name', e.target.value)} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>종류</span>
          <Select
            value={f.kind}
            onChange={(v) => set('kind', v)}
            style={{ width: '100%' }}
            options={[
              { label: 'Chat', value: 'chat' },
              { label: 'Embedding', value: 'embedding' },
            ]}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>프로바이더</span>
          <Select
            value={f.provider_id || undefined}
            onChange={(v) => set('provider_id', v)}
            style={{ width: '100%' }}
            placeholder={providers.length ? '연결처 선택' : '먼저 프로바이더를 등록하세요'}
            options={providers.map((p) => ({
              label: `${p.name} — ${p.base_url}`,
              value: p.id,
            }))}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>모델 ID</span>
          <Input placeholder="mlx-community/..." value={f.model_id} onChange={(e) => set('model_id', e.target.value)} />
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Switch checked={f.is_default} onChange={(v) => set('is_default', v)} />
          <span style={{ fontSize: 14, fontWeight: 500 }}>기본 모델</span>
        </label>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Button
            icon={<Icon name="thunderbolt" />}
            loading={testing}
            disabled={testDisabled}
            onClick={runTest}
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
      </div>
    </Modal>
  )
}

export default function ModelsView() {
  const [models, setModels] = useState<Model[]>([])
  const [providers, setProviders] = useState<Provider[]>([])
  const [formOpen, setFormOpen] = useState(false)
  const [confirmDel, setConfirmDel] = useState<Model | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)

  const load = async () => {
    try {
      const [ms, ps] = await Promise.all([listModels(), listProviders()])
      setModels(ms)
      setProviders(ps)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '모델을 불러오지 못했습니다')
    }
  }

  useEffect(() => {
    void load()
    /* eslint-disable-next-line */
  }, [])

  const openCreate = () => {
    if (!providers.length) {
      message.warning('먼저 프로바이더를 등록하세요')
      return
    }
    setFormOpen(true)
  }

  const create = async (data: ModelFormData) => {
    if (!data.name.trim() || !data.model_id.trim() || !data.provider_id) {
      message.warning('이름·프로바이더·모델 ID를 입력하세요')
      return
    }
    try {
      await createModel({
        name: data.name.trim(),
        provider_id: data.provider_id,
        model_id: data.model_id.trim(),
        kind: data.kind,
        is_default: data.is_default,
        params: {},
      })
      await load()
      setFormOpen(false)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '모델 등록에 실패했습니다')
    }
  }

  const runRowTest = async (m: Model) => {
    if (testingId) return
    setTestingId(m.id)
    try {
      const result = await testSavedModel(m.id)
      // 연결됐어도 모델이 목록에 없으면(미발견) 경고로 — '이 모델 쓸 수 있나' 관점.
      if (result.ok && result.modelAvailable) message.success(result.detail)
      else message.warning(result.detail)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '연결 테스트에 실패했습니다')
    } finally {
      setTestingId(null)
    }
  }

  const doDelete = async () => {
    if (!confirmDel) return
    try {
      await deleteModel(confirmDel.id)
      await load()
      setConfirmDel(null)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '삭제에 실패했습니다')
    }
  }

  const columns: Column<Model>[] = [
    {
      key: 'name',
      title: '이름',
      render: (m) => <span style={{ fontWeight: 500, color: 'var(--color-text-heading)' }}>{m.name}</span>,
    },
    {
      key: 'kind',
      title: '종류',
      width: 120,
      render: (m) =>
        m.kind === 'chat' ? <Tag color="blue">Chat</Tag> : <Tag color="cyan">Embedding</Tag>,
    },
    {
      key: 'model_id',
      title: '모델 ID',
      render: (m) => <code style={codeStyle}>{m.model_id}</code>,
    },
    {
      key: 'provider',
      title: '프로바이더',
      render: (m) => (
        <span>
          <Tag color="geekblue">{m.provider_name}</Tag>
          <code style={{ ...codeStyle, fontSize: 12, color: 'var(--color-text-tertiary)' }}>{m.base_url}</code>
        </span>
      ),
    },
    {
      key: 'is_default',
      title: '기본',
      width: 90,
      render: (m) =>
        m.is_default ? <Tag color="green">기본</Tag> : <span style={{ color: 'var(--color-text-quaternary)' }}>—</span>,
    },
    {
      key: 'actions',
      title: '',
      width: 110,
      align: 'right',
      render: (m) => (
        <span onClick={(e) => e.stopPropagation()}>
          <Button
            type="text"
            size="small"
            icon={<Icon name="thunderbolt" />}
            loading={testingId === m.id}
            disabled={testingId !== null && testingId !== m.id}
            onClick={() => runRowTest(m)}
          >
            테스트
          </Button>
          <Button type="text" size="small" danger icon={<Icon name="delete" />} onClick={() => setConfirmDel(m)} />
        </span>
      ),
    },
  ]

  return (
    <Page
      title="모델"
      subtitle="LLM·임베딩 모델 설정 — 에이전트 실행에 사용"
      actions={
        <Button type="primary" icon={<Icon name="plus" />} onClick={openCreate}>
          모델 등록
        </Button>
      }
    >
      <DataTable columns={columns} rows={models} />

      <RegisterModal open={formOpen} providers={providers} onCancel={() => setFormOpen(false)} onCreate={create} />

      <Modal
        open={!!confirmDel}
        title="모델을 삭제할까요?"
        okText="삭제"
        cancelText="취소"
        onCancel={() => setConfirmDel(null)}
        onOk={doDelete}
      >
        {confirmDel ? (
          <div>
            <b>{confirmDel.name}</b>을(를) 삭제합니다. 이 모델을 사용하는 에이전트는 실행에 실패할 수 있습니다.
          </div>
        ) : null}
      </Modal>
    </Page>
  )
}
