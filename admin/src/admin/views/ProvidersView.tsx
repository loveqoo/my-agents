/* my-agents admin — Providers view: LLM 연결처(엔드포인트+자격증명) 레지스트리 (스펙 035).
   provider 1회 등록 → 하위 모델이 base_url/api_key를 상속. 등록/수정 모달 + 연결 테스트.
   삭제는 매달린 모델이 있으면 서버가 409로 차단(RESTRICT). */
import { useState, useEffect } from 'react'
import { Tag, Button, Modal, Input, message } from 'antd'
import { Page, DataTable, type Column } from '../shared'
import { Icon } from '../icons'
import {
  listProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  testProviderConfig,
  testSavedProvider,
  type Provider,
  type ModelProbeResult,
} from '../../api'

/* 등록/수정 폼 shape. api_key는 비워두면(수정 시) 기존 키 보존 — 마스킹 값을 그대로 전송. */
interface ProviderFormData {
  name: string
  protocol: string
  base_url: string
  api_key: string
}

const blankForm: ProviderFormData = {
  name: '',
  protocol: 'openai-compatible',
  base_url: '',
  api_key: '',
}

const codeStyle = { fontFamily: 'var(--font-family-code)', fontSize: 13 }

/* ---- provider 등록/수정 모달 ---- */
function EditModal({
  open,
  editing,
  onCancel,
  onSubmit,
}: {
  open: boolean
  editing: Provider | null
  onCancel: () => void
  onSubmit: (data: ProviderFormData) => void
}) {
  const [f, setF] = useState<ProviderFormData>(blankForm)
  const [testing, setTesting] = useState(false)
  const [probe, setProbe] = useState<ModelProbeResult | null>(null)

  useEffect(() => {
    if (open) {
      // 수정 시 기존 값으로 채우되, 마스킹된 api_key는 그대로 둬서 "보존" 신호로 재전송한다.
      setF(
        editing
          ? {
              name: editing.name,
              protocol: editing.protocol,
              base_url: editing.base_url,
              api_key: editing.api_key ?? '',
            }
          : blankForm,
      )
      setProbe(null)
    }
  }, [open, editing])

  const set = <K extends keyof ProviderFormData>(k: K, v: ProviderFormData[K]) => {
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

  const testDisabled = testing || !f.base_url.trim()

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
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>이름</span>
          <Input
            placeholder="예: OpenAI (프로덕션)"
            value={f.name}
            onChange={(e) => set('name', e.target.value)}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>프로토콜</span>
          <Input
            placeholder="openai-compatible"
            value={f.protocol}
            onChange={(e) => set('protocol', e.target.value)}
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
          <span style={{ fontSize: 14, fontWeight: 500 }}>API 키</span>
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

export default function ProvidersView() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Provider | null>(null)
  const [confirmDel, setConfirmDel] = useState<Provider | null>(null)
  const [testingId, setTestingId] = useState<string | null>(null)

  const load = async () => {
    try {
      setProviders(await listProviders())
    } catch (e) {
      message.error(e instanceof Error ? e.message : '프로바이더를 불러오지 못했습니다')
    }
  }

  useEffect(() => {
    void load()
    /* eslint-disable-next-line */
  }, [])

  const openCreate = () => {
    setEditing(null)
    setFormOpen(true)
  }
  const openEdit = (p: Provider) => {
    setEditing(p)
    setFormOpen(true)
  }

  const submit = async (data: ProviderFormData) => {
    if (!data.name.trim() || !data.base_url.trim()) {
      message.warning('이름과 Base URL을 입력하세요')
      return
    }
    const body = {
      name: data.name.trim(),
      protocol: data.protocol.trim() || 'openai-compatible',
      base_url: data.base_url.trim(),
      api_key: data.api_key,
    }
    try {
      if (editing) await updateProvider(editing.id, body)
      else await createProvider(body)
      await load()
      setFormOpen(false)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '저장에 실패했습니다')
    }
  }

  const runRowTest = async (p: Provider) => {
    if (testingId) return
    setTestingId(p.id)
    try {
      const result = await testSavedProvider(p.id)
      if (result.ok) message.success(result.detail)
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
      await deleteProvider(confirmDel.id)
      await load()
      setConfirmDel(null)
    } catch (e) {
      // 매달린 모델이 있으면 서버가 409 + 안내 메시지를 준다.
      message.error(e instanceof Error ? e.message : '삭제에 실패했습니다')
    }
  }

  const columns: Column<Provider>[] = [
    {
      key: 'name',
      title: '이름',
      render: (p) => <span style={{ fontWeight: 500, color: 'var(--color-text-heading)' }}>{p.name}</span>,
    },
    {
      key: 'protocol',
      title: '프로토콜',
      width: 160,
      render: (p) => <Tag color="geekblue">{p.protocol}</Tag>,
    },
    {
      key: 'base_url',
      title: 'Base URL',
      render: (p) => (
        <code style={{ ...codeStyle, fontSize: 12, color: 'var(--color-text-tertiary)' }}>{p.base_url}</code>
      ),
    },
    {
      key: 'api_key',
      title: '키',
      width: 120,
      render: (p) =>
        p.api_key ? (
          <code style={{ ...codeStyle, fontSize: 12, color: 'var(--color-text-secondary)' }}>{p.api_key}</code>
        ) : (
          <span style={{ color: 'var(--color-text-quaternary)' }}>—</span>
        ),
    },
    {
      key: 'modelCount',
      title: '모델',
      width: 90,
      render: (p) =>
        p.modelCount > 0 ? (
          <Tag color="blue">{p.modelCount}개</Tag>
        ) : (
          <span style={{ color: 'var(--color-text-quaternary)' }}>0</span>
        ),
    },
    {
      key: 'actions',
      title: '',
      width: 150,
      align: 'right',
      render: (p) => (
        <span onClick={(e) => e.stopPropagation()}>
          <Button
            type="text"
            size="small"
            icon={<Icon name="thunderbolt" />}
            loading={testingId === p.id}
            disabled={testingId !== null && testingId !== p.id}
            onClick={() => runRowTest(p)}
          >
            테스트
          </Button>
          <Button type="text" size="small" icon={<Icon name="edit" />} onClick={() => openEdit(p)} />
          <Button type="text" size="small" danger icon={<Icon name="delete" />} onClick={() => setConfirmDel(p)} />
        </span>
      ),
    },
  ]

  return (
    <Page
      title="프로바이더"
      subtitle="LLM 연결처(엔드포인트+자격증명) — 모델이 base_url/키를 상속"
      actions={
        <Button type="primary" icon={<Icon name="plus" />} onClick={openCreate}>
          프로바이더 등록
        </Button>
      }
    >
      <DataTable columns={columns} rows={providers} />

      <EditModal open={formOpen} editing={editing} onCancel={() => setFormOpen(false)} onSubmit={submit} />

      <Modal
        open={!!confirmDel}
        title="프로바이더를 삭제할까요?"
        okText="삭제"
        cancelText="취소"
        onCancel={() => setConfirmDel(null)}
        onOk={doDelete}
      >
        {confirmDel ? (
          <div>
            <b>{confirmDel.name}</b>을(를) 삭제합니다.
            {confirmDel.modelCount > 0 ? (
              <div style={{ marginTop: 8, color: 'var(--color-error)' }}>
                매달린 모델 {confirmDel.modelCount}개가 있어 삭제가 차단됩니다. 먼저 모델을 제거하세요.
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </Page>
  )
}
