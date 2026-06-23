/* my-agents admin — Models view: LLM·임베딩 모델 레지스트리.
   목록 → 등록 모달. 에이전트 실행에 사용되는 chat/embedding 모델을 관리한다. */
import { useState, useEffect } from 'react'
import { Tag, Button, Modal, Input, Select, Switch, message } from 'antd'
import { Page, DataTable, type Column } from '../shared'
import { Icon } from '../icons'
import { listModels, createModel, deleteModel, type Model } from '../../api'

/* 등록 폼 데이터 shape. */
interface ModelFormData {
  name: string
  kind: 'chat' | 'embedding'
  base_url: string
  model_id: string
  api_key: string
  is_default: boolean
}

const blankForm: ModelFormData = {
  name: '',
  kind: 'chat',
  base_url: '',
  model_id: '',
  api_key: '',
  is_default: false,
}

const codeStyle = { fontFamily: 'var(--font-family-code)', fontSize: 13 }

/* ---- 모델 등록 모달 ---- */
function RegisterModal({
  open,
  onCancel,
  onCreate,
}: {
  open: boolean
  onCancel: () => void
  onCreate: (data: ModelFormData) => void
}) {
  const [f, setF] = useState<ModelFormData>(blankForm)

  useEffect(() => {
    if (open) setF(blankForm)
  }, [open])

  const set = <K extends keyof ModelFormData>(k: K, v: ModelFormData[K]) =>
    setF((s) => ({ ...s, [k]: v }))

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
          <span style={{ fontSize: 14, fontWeight: 500 }}>Base URL</span>
          <Input
            prefix={<Icon name="global" />}
            placeholder="http://localhost:8045/v1"
            value={f.base_url}
            onChange={(e) => set('base_url', e.target.value)}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>모델 ID</span>
          <Input placeholder="mlx-community/..." value={f.model_id} onChange={(e) => set('model_id', e.target.value)} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>API 키</span>
          <Input.Password prefix={<Icon name="key" />} value={f.api_key} onChange={(e) => set('api_key', e.target.value)} />
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Switch checked={f.is_default} onChange={(v) => set('is_default', v)} />
          <span style={{ fontSize: 14, fontWeight: 500 }}>기본 모델</span>
        </label>
      </div>
    </Modal>
  )
}

export default function ModelsView() {
  const [models, setModels] = useState<Model[]>([])
  const [formOpen, setFormOpen] = useState(false)
  const [confirmDel, setConfirmDel] = useState<Model | null>(null)

  const load = async () => {
    try {
      setModels(await listModels())
    } catch (e) {
      message.error(e instanceof Error ? e.message : '모델을 불러오지 못했습니다')
    }
  }

  useEffect(() => {
    void load()
    /* eslint-disable-next-line */
  }, [])

  const create = async (data: ModelFormData) => {
    if (!data.name.trim() || !data.model_id.trim()) {
      message.warning('이름과 모델 ID를 입력하세요')
      return
    }
    try {
      await createModel({
        name: data.name.trim(),
        provider: 'openai-compatible',
        base_url: data.base_url.trim(),
        api_key: data.api_key,
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
      key: 'base_url',
      title: 'Base URL',
      render: (m) => (
        <code style={{ ...codeStyle, fontSize: 12, color: 'var(--color-text-tertiary)' }}>{m.base_url}</code>
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
      key: 'api_key',
      title: '키',
      render: (m) =>
        m.api_key ? (
          <code style={{ ...codeStyle, fontSize: 12, color: 'var(--color-text-secondary)' }}>{m.api_key}</code>
        ) : (
          <span style={{ color: 'var(--color-text-quaternary)' }}>—</span>
        ),
    },
    {
      key: 'actions',
      title: '',
      width: 60,
      align: 'right',
      render: (m) => (
        <span onClick={(e) => e.stopPropagation()}>
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
        <Button type="primary" icon={<Icon name="plus" />} onClick={() => setFormOpen(true)}>
          모델 등록
        </Button>
      }
    >
      <DataTable columns={columns} rows={models} />

      <RegisterModal open={formOpen} onCancel={() => setFormOpen(false)} onCreate={create} />

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
