/* my-agents admin — Building blocks (재료) browser: personas, memory policies,
   permissions, MCP servers. Category tabs → list → detail drawer. */
import { useState, useEffect } from 'react'
import { Tag, Button, Tabs, Switch, Modal, Input, Select, Checkbox, Alert, message } from 'antd'
import { Page, DataTable, Drawer, Desc, type Column } from '../shared'
import { Icon } from '../icons'
import { MCP_STATUS, VECTOR_STATUS, APPROVER, type BlockItem, type BlockCategory } from '../mockData'
import {
  getBlocks,
  createMcp,
  updateMcp,
  deleteMcp,
  publishMcp,
  createBlockItem,
  updateBlockItem,
  deleteBlockItem,
} from '../../api'

const { TextArea } = Input

/* 백엔드 McpServerIn payload — snake_case로 in. */
interface McpServerIn {
  name: string
  source: string
  transport: string
  url?: string
  endpoint?: string
  tools: string[]
  enabled_tools: string[]
  status: string
  published: boolean
  auth?: string
}

/* 비-MCP 카테고리 → 백엔드 resource 경로 매핑. */
const RESOURCE_BY_CAT: Record<string, string> = {
  persona: 'personas',
  memory: 'memory-types',
  embedding: 'vector-tables',
  permission: 'permissions',
}

type McpFormState = {
  mode: 'register' | 'edit'
  source?: string
  item?: BlockItem
}

type McpFormData = {
  id?: string
  name: string
  transport: string
  url: string
  auth: string
  tools: string[]
  enabledTools: string[]
  usedBy?: number
  published?: boolean
  endpoint?: string
  toolsText?: string
}

/* MCP register/edit connection form. mode: "register" (new) | "edit". */
function McpForm({
  form,
  onCancel,
  onSave,
}: {
  form: McpFormState | null
  onCancel: () => void
  onSave: (item: BlockItem) => void
}) {
  const external = !!(form && (form.source === 'external' || (form.item && form.item.source === 'external')))
  const blank: McpFormData = { name: '', transport: external ? 'http' : 'stdio', url: '', auth: 'None', tools: [], enabledTools: [] }
  const [f, setF] = useState<McpFormData>(blank)
  useEffect(() => {
    if (!form) return
    if (form.mode === 'edit' && form.item) {
      const m = form.item
      setF({
        id: m.id,
        name: m.name,
        transport: m.transport || 'stdio',
        url: m.url || '',
        auth: m.auth || 'None',
        tools: [...(m.tools || [])],
        enabledTools: [...(m.enabledTools || m.tools || [])],
        usedBy: m.usedBy,
        published: m.published,
        endpoint: m.endpoint,
      })
    } else {
      setF({ ...blank, transport: external ? 'http' : 'stdio' })
    }
    /* eslint-disable-next-line */
  }, [form])
  if (!form) return null
  const set = <K extends keyof McpFormData>(k: K, v: McpFormData[K]) => setF((s) => ({ ...s, [k]: v }))
  const toggleTool = (t: string) =>
    setF((s) => ({
      ...s,
      enabledTools: s.enabledTools.includes(t) ? s.enabledTools.filter((x) => x !== t) : [...s.enabledTools, t],
    }))
  const isExternal = external
  const isEdit = form.mode === 'edit'

  const submit = () => {
    const id = isEdit ? f.id! : 'mcp-' + Date.now()
    const tools = isEdit ? f.tools : (f.toolsText || '').split(',').map((x) => x.trim()).filter(Boolean)
    const enabledTools = isEdit ? f.enabledTools : tools
    const item: BlockItem = {
      id,
      name: f.name.trim() || (isExternal ? 'external-mcp' : 'new-server'),
      source: isExternal ? 'external' : 'local',
      transport: f.transport,
      tools,
      enabledTools,
      usedBy: isEdit ? f.usedBy ?? 0 : 0,
      status: 'connected',
      updated: 'just now',
      published: isEdit ? !!f.published : false,
      url: isExternal ? (f.url || 'mcp://remote/endpoint') : undefined,
      auth: isExternal ? f.auth : undefined,
      endpoint: isExternal ? undefined : (f.endpoint || ('mcp://my-agents.local/' + (f.name.trim() || 'new-server'))),
    }
    onSave(item)
  }

  return (
    <Modal
      open={!!form}
      width={520}
      title={isEdit ? '연결 편집 · ' + f.name : isExternal ? '외부 MCP 등록' : '새 로컬 MCP 서버'}
      okText={isEdit ? '연결 저장' : '등록'}
      cancelText="취소"
      onCancel={onCancel}
      onOk={submit}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '60vh', overflow: 'auto' }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 0 }}
          message={
            isExternal
              ? '다른 곳에서 프로토콜로 공개한 MCP 서버에 연결합니다. 그 도구를 소비합니다.'
              : '직접 운영하는 서버를 등록합니다. 나중에 MCP로 외부 공개할 수 있습니다.'
          }
        />
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>이름</span>
          <Input
            placeholder={isExternal ? '예: partner-crm' : '예: filesystem'}
            value={f.name}
            onChange={(e) => set('name', e.target.value)}
          />
        </label>
        {isExternal ? (
          <>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 14, fontWeight: 500 }}>MCP URL</span>
              <Input
                prefix={<Icon name="global" />}
                placeholder="mcp://host/endpoint"
                value={f.url}
                onChange={(e) => set('url', e.target.value)}
              />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 14, fontWeight: 500 }}>인증</span>
              <Select
                value={f.auth}
                onChange={(v) => set('auth', v)}
                style={{ width: '100%' }}
                options={[
                  { label: '없음', value: 'None' },
                  { label: 'Bearer 토큰', value: 'Bearer ****' },
                  { label: 'OAuth', value: 'OAuth' },
                ]}
              />
            </label>
          </>
        ) : (
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>전송 방식</span>
            <Select
              value={f.transport}
              onChange={(v) => set('transport', v)}
              style={{ width: '100%' }}
              options={[
                { label: 'stdio', value: 'stdio' },
                { label: 'http', value: 'http' },
              ]}
            />
          </label>
        )}
        {isEdit ? (
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>활성 도구</span>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px' }}>
              {f.tools.map((t) => (
                <Checkbox key={t} checked={f.enabledTools.includes(t)} onChange={() => toggleTool(t)}>
                  {t}
                </Checkbox>
              ))}
            </div>
          </label>
        ) : (
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>
              도구{' '}
              <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>
                (쉼표로 구분{isExternal ? '; 서버에서 자동 발견' : ''})
              </span>
            </span>
            <Input
              placeholder="search, read, list"
              value={f.toolsText || ''}
              onChange={(e) => set('toolsText', e.target.value)}
            />
          </label>
        )}
      </div>
    </Modal>
  )
}

/* 페르소나 등록/편집 폼 — 이름·톤·본문(시스템 프롬프트). mode로 생성/수정 공용. */
type PersonaFormState = { mode: 'create' | 'edit'; item?: BlockItem }

function PersonaForm({
  form,
  onCancel,
  onSave,
}: {
  form: PersonaFormState | null
  onCancel: () => void
  onSave: (data: { id?: string; name: string; tone: string; body: string }) => void
}) {
  const [name, setName] = useState('')
  const [tone, setTone] = useState('')
  const [body, setBody] = useState('')
  useEffect(() => {
    if (!form) return
    if (form.mode === 'edit' && form.item) {
      setName(form.item.name ?? '')
      setTone(form.item.tone ?? '')
      setBody(form.item.body ?? '')
    } else {
      setName('')
      setTone('')
      setBody('')
    }
  }, [form])
  if (!form) return null
  const isEdit = form.mode === 'edit'
  const submit = () => {
    if (!name.trim()) {
      message.warning('이름을 입력하세요')
      return
    }
    onSave({ id: isEdit ? form.item?.id : undefined, name: name.trim(), tone: tone.trim(), body })
  }
  return (
    <Modal
      open={!!form}
      width={560}
      title={isEdit ? '페르소나 편집 · ' + (form.item?.name ?? '') : '새 페르소나'}
      okText={isEdit ? '저장' : '등록'}
      cancelText="취소"
      onCancel={onCancel}
      onOk={submit}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '64vh', overflow: 'auto' }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 0 }}
          message="페르소나는 에이전트의 성격·말투·역할을 정의하는 시스템 프롬프트입니다. 에이전트 편집기에서 이름으로 선택해 재사용합니다."
        />
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>이름</span>
          <Input placeholder="예: 친절한 고양이" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>
            톤 <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(선택 · 목록 표시용 라벨)</span>
          </span>
          <Input placeholder="예: 친근함, 격식체, 간결함" value={tone} onChange={(e) => setTone(e.target.value)} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>본문 (시스템 프롬프트)</span>
          <TextArea
            rows={8}
            placeholder={'예: 너는 고양이다. 모든 문장 끝에 "냐옹"을 붙여라.'}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            style={{ fontFamily: 'var(--font-family-code)', fontSize: 13 }}
          />
        </label>
      </div>
    </Modal>
  )
}

export default function BlocksView() {
  const [data, setData] = useState<Record<string, BlockCategory>>({})
  const [cat, setCat] = useState('persona')
  const [detail, setDetail] = useState<BlockItem | null>(null)
  const [mcpForm, setMcpForm] = useState<McpFormState | null>(null) // { mode:'register'|'edit', item? }
  const [personaForm, setPersonaForm] = useState<PersonaFormState | null>(null)

  /* 새 데이터로 열린 drawer의 detail을 id로 재조회(없으면 닫음). */
  const syncDetail = (next: Record<string, BlockCategory>) => {
    setDetail((dt) => {
      if (!dt) return dt
      for (const c of Object.keys(next)) {
        const found = next[c].items.find((it) => it.id === dt.id)
        if (found) return found
      }
      return null
    })
  }

  const loadBlocks = async () => {
    try {
      const next = await getBlocks()
      setData(next)
      syncDetail(next)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '블록을 불러오지 못했습니다')
    }
  }

  useEffect(() => {
    void loadBlocks()
    /* eslint-disable-next-line */
  }, [])

  const def = data[cat]

  const togglePublish = async (id: string) => {
    const current = data.mcp?.items.find((m) => m.id === id)
    if (!current) return
    try {
      await publishMcp(id, !current.published)
      await loadBlocks()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '공개 상태 변경에 실패했습니다')
    }
  }

  const upsertMcp = async (item: BlockItem) => {
    const isEdit = !!data.mcp?.items.some((m) => m.id === item.id)
    const payload: McpServerIn = {
      name: item.name,
      source: item.source ?? 'local',
      transport: item.transport ?? 'stdio',
      url: item.url,
      endpoint: item.endpoint,
      tools: item.tools ?? [],
      enabled_tools: item.enabledTools ?? [],
      status: item.status ?? 'connected',
      published: !!item.published,
      auth: item.auth,
    }
    try {
      if (isEdit) await updateMcp(item.id, payload)
      else await createMcp(payload)
      await loadBlocks()
      setMcpForm(null)
    } catch (e) {
      message.error(e instanceof Error ? e.message : 'MCP 저장에 실패했습니다')
    }
  }

  const deleteCurrent = async () => {
    if (!detail) return
    try {
      if (cat === 'mcp') await deleteMcp(detail.id)
      else {
        const resource = RESOURCE_BY_CAT[cat]
        if (!resource) return
        await deleteBlockItem(resource, detail.id)
      }
      await loadBlocks()
      setDetail(null)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '삭제에 실패했습니다')
    }
  }

  const createCurrent = async () => {
    /* persona는 전용 폼으로 작성 — 나머지 카테고리는 빈 항목 생성(추후 전용 폼). */
    if (cat === 'persona') {
      setPersonaForm({ mode: 'create' })
      return
    }
    const resource = RESOURCE_BY_CAT[cat]
    if (!resource) return
    try {
      await createBlockItem(resource, { name: '새 항목' })
      await loadBlocks()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '생성에 실패했습니다')
    }
  }

  const savePersona = async (data: { id?: string; name: string; tone: string; body: string }) => {
    const payload = { name: data.name, tone: data.tone || null, body: data.body }
    try {
      if (data.id) await updateBlockItem('personas', data.id, payload)
      else await createBlockItem('personas', payload)
      await loadBlocks()
      setPersonaForm(null)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '페르소나 저장에 실패했습니다')
    }
  }

  const colsFor = (key: string): Column<BlockItem>[] => {
    if (key === 'mcp')
      return [
        {
          key: 'name',
          title: '서버',
          render: (r) => (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <code style={{ fontFamily: 'var(--font-family-code)', color: 'var(--cyan-7)', fontSize: 13 }}>{r.name}</code>
              {r.source === 'external' ? <Tag color="purple">외부</Tag> : <Tag>로컬</Tag>}
            </span>
          ),
        },
        { key: 'transport', title: '전송', width: 100, render: (r) => <Tag>{r.transport}</Tag> },
        {
          key: 'tools',
          title: '도구',
          render: (r) => (
            <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
              {(r.tools || []).map((t) =>
                (r.enabledTools || r.tools || []).includes(t) ? (
                  <Tag key={t} color="geekblue">{t}</Tag>
                ) : (
                  <Tag key={t}>{t}</Tag>
                ),
              )}
            </span>
          ),
        },
        {
          key: 'status',
          title: '상태',
          width: 110,
          render: (r) => {
            const s = MCP_STATUS[r.status!]
            return <Tag color={s.tag}>{s.label}</Tag>
          },
        },
        {
          key: 'published',
          title: '공개',
          width: 116,
          render: (r) =>
            r.source === 'external' ? (
              <span style={{ color: 'var(--color-text-quaternary)' }}>—</span>
            ) : r.published ? (
              <Tag color="green">MCP · 공개</Tag>
            ) : (
              <span style={{ color: 'var(--color-text-quaternary)' }}>비공개</span>
            ),
        },
        {
          key: 'usedBy',
          title: '사용',
          width: 70,
          align: 'right',
          render: (r) => <span style={{ color: 'var(--color-text-secondary)' }}>{r.usedBy}</span>,
        },
      ]
    if (key === 'embedding')
      return [
        {
          key: 'name',
          title: '테이블',
          render: (r) => (
            <code style={{ fontFamily: 'var(--font-family-code)', color: 'var(--cyan-7)', fontSize: 13 }}>{r.name}</code>
          ),
        },
        { key: 'model', title: '임베딩 모델', render: (r) => <Tag color="geekblue">{r.model}</Tag> },
        {
          key: 'source',
          title: '출처',
          render: (r) => (
            <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 12, color: 'var(--color-text-secondary)' }}>
              {r.source}
            </code>
          ),
        },
        {
          key: 'rows',
          title: '행',
          width: 90,
          align: 'right',
          render: (r) => (
            <span style={{ fontFamily: 'var(--font-family-code)', color: 'var(--color-text-secondary)' }}>
              {r.rows?.toLocaleString()}
            </span>
          ),
        },
        {
          key: 'status',
          title: '상태',
          width: 110,
          render: (r) => {
            const s = VECTOR_STATUS[r.status!]
            return <Tag color={s.tag}>{s.label}</Tag>
          },
        },
        {
          key: 'usedBy',
          title: '사용',
          width: 70,
          align: 'right',
          render: (r) => <span style={{ color: 'var(--color-text-secondary)' }}>{r.usedBy}</span>,
        },
      ]
    if (key === 'permission')
      return [
        {
          key: 'name',
          title: '권한',
          render: (r) => (
            <code style={{ fontFamily: 'var(--font-family-code)', color: 'var(--geekblue-7)', fontSize: 13 }}>{r.name}</code>
          ),
        },
        { key: 'scope', title: '범위', width: 130, render: (r) => <Tag>{r.scope}</Tag> },
        {
          key: 'approver',
          title: '승인자',
          width: 120,
          render: (r) => {
            const a = APPROVER[r.approver!]
            return (
              <Tag color={a.tag}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <Icon name={a.icon!} size={11} />
                  {a.label}
                </span>
              </Tag>
            )
          },
        },
        { key: 'body', title: '설명', render: (r) => <span style={{ color: 'var(--color-text-secondary)' }}>{r.body}</span> },
        {
          key: 'usedBy',
          title: '사용',
          width: 80,
          align: 'right',
          render: (r) => <span style={{ color: 'var(--color-text-secondary)' }}>{r.usedBy}</span>,
        },
      ]
    // persona + memory
    return [
      {
        key: 'name',
        title: (def?.label ?? '').replace(/s$/, ''),
        render: (r) => <span style={{ fontWeight: 500, color: 'var(--color-text-heading)' }}>{r.name}</span>,
      },
      {
        key: 'meta',
        title: key === 'persona' ? '톤' : '범위',
        width: 200,
        render: (r) => <Tag color={key === 'persona' ? 'magenta' : 'purple'}>{r.tone || r.scope}</Tag>,
      },
      {
        key: 'usedBy',
        title: '사용',
        width: 100,
        render: (r) => <span style={{ color: 'var(--color-text-secondary)' }}>{r.usedBy}개 에이전트</span>,
      },
      {
        key: 'updated',
        title: '수정',
        width: 120,
        align: 'right',
        render: (r) => <span style={{ color: 'var(--color-text-tertiary)' }}>{r.updated}</span>,
      },
    ]
  }

  const tabItems = Object.keys(data).map((k) => ({
    key: k,
    label: (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
        <Icon name={data[k].icon} size={14} style={{ color: data[k].color }} />
        {data[k].label}
        <Tag>{data[k].items.length}</Tag>
      </span>
    ),
  }))

  return (
    <Page
      title="빌딩 블록"
      subtitle="에이전트를 구성하는 재사용 재료 — 둘러보고 에이전트 편집기에서 조립하세요"
      actions={
        cat === 'mcp' ? (
          <span style={{ display: 'inline-flex', gap: 8 }}>
            <Button icon={<Icon name="global" />} onClick={() => setMcpForm({ mode: 'register', source: 'external' })}>
              외부 등록
            </Button>
            <Button type="primary" icon={<Icon name="plus" />} onClick={() => setMcpForm({ mode: 'register', source: 'local' })}>
              새 서버
            </Button>
          </span>
        ) : (
          <Button type="primary" icon={<Icon name="plus" />} onClick={() => void createCurrent()}>
            새 항목
          </Button>
        )
      }
    >
      <Tabs
        activeKey={cat}
        onChange={(k) => {
          setCat(k)
          setDetail(null)
        }}
        items={tabItems}
      />
      <div style={{ marginTop: 4, marginBottom: 14, color: 'var(--color-text-tertiary)', fontSize: 14 }}>{def?.desc}</div>
      <DataTable columns={colsFor(cat)} rows={def?.items ?? []} onRowClick={setDetail} />

      <Drawer
        open={!!detail}
        title={detail ? detail.name : ''}
        width={440}
        onClose={() => setDetail(null)}
        footer={
          <>
            <Button danger icon={<Icon name="delete" />} onClick={() => void deleteCurrent()}>
              삭제
            </Button>
            {cat === 'mcp' ? (
              <Button type="primary" icon={<Icon name="edit" />} onClick={() => detail && setMcpForm({ mode: 'edit', item: detail })}>
                연결 편집
              </Button>
            ) : cat === 'persona' ? (
              <Button type="primary" icon={<Icon name="edit" />} onClick={() => detail && setPersonaForm({ mode: 'edit', item: detail })}>
                편집
              </Button>
            ) : (
              <Button type="primary" icon={<Icon name="edit" />} disabled>
                편집
              </Button>
            )}
          </>
        }
      >
        {detail ? (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
              <span
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: 9,
                  background: def?.color,
                  color: '#fff',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Icon name={def?.icon ?? ''} size={18} />
              </span>
              <div style={{ fontSize: 16, fontWeight: 600 }}>{detail.name}</div>
            </div>
            {detail.model ? (
              <Desc label="임베딩 모델">
                <Tag color="geekblue">{detail.model}</Tag>
              </Desc>
            ) : null}
            {detail.source ? (
              <Desc label="출처">
                <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 12 }}>{detail.source}</code>
              </Desc>
            ) : null}
            {detail.dims ? <Desc label="차원">{detail.dims.toLocaleString()}차원</Desc> : null}
            {detail.rows != null ? <Desc label="행 수">{detail.rows.toLocaleString()}개 벡터</Desc> : null}
            {detail.status && VECTOR_STATUS[detail.status] ? (
              <Desc label="상태">
                <Tag color={VECTOR_STATUS[detail.status].tag}>{VECTOR_STATUS[detail.status].label}</Tag>
              </Desc>
            ) : null}
            {detail.tone ? (
              <Desc label="톤">
                <Tag color="magenta">{detail.tone}</Tag>
              </Desc>
            ) : null}
            {detail.scope ? (
              <Desc label="범위">{cat === 'memory' ? <Tag color="purple">{detail.scope}</Tag> : <Tag>{detail.scope}</Tag>}</Desc>
            ) : null}
            {detail.approver
              ? (() => {
                  const a = APPROVER[detail.approver!]
                  return (
                    <Desc label="승인자">
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                        <Tag color={a.tag}>
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                            <Icon name={a.icon!} size={11} />
                            {a.label}
                          </span>
                        </Tag>
                        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{a.desc}</span>
                      </span>
                    </Desc>
                  )
                })()
              : null}
            {detail.transport ? (
              <Desc label="전송">
                <Tag>{detail.transport}</Tag>
              </Desc>
            ) : null}
            {cat === 'mcp' && detail.source ? (
              <Desc label="소스">
                {detail.source === 'external' ? (
                  <Tag color="purple">외부 · URL로 등록</Tag>
                ) : (
                  <Tag>로컬 · 자체 운영</Tag>
                )}
              </Desc>
            ) : null}
            {detail.url ? (
              <Desc label="URL">
                <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 12, wordBreak: 'break-all' }}>{detail.url}</code>
              </Desc>
            ) : null}
            {detail.auth ? (
              <Desc label="인증">
                <Tag>{detail.auth}</Tag>
              </Desc>
            ) : null}
            {detail.tools ? (
              <Desc label="도구">
                <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
                  {detail.tools.map((t) => {
                    const enabled = (detail.enabledTools || detail.tools || []).includes(t)
                    const label = t + (detail.enabledTools && !detail.enabledTools.includes(t) ? ' (비활성)' : '')
                    return enabled ? (
                      <Tag key={t} color="geekblue">{label}</Tag>
                    ) : (
                      <Tag key={t}>{label}</Tag>
                    )
                  })}
                </span>
              </Desc>
            ) : null}
            {cat === 'mcp' && detail.status ? (
              <Desc label="상태">
                <Tag color={MCP_STATUS[detail.status].tag}>{MCP_STATUS[detail.status].label}</Tag>
              </Desc>
            ) : null}
            <Desc label="사용">{detail.usedBy}개 에이전트</Desc>
            <Desc label="수정">{detail.updated}</Desc>
            {cat === 'mcp' && detail.source !== 'external' ? (
              <div
                style={{
                  marginTop: 18,
                  padding: 16,
                  border: '1px solid var(--color-border-secondary)',
                  borderRadius: 'var(--radius-lg)',
                  background: 'var(--gray-2)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <Icon name="global" size={16} style={{ color: 'var(--cyan-7)' }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 500 }}>외부 공개</div>
                    <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                      이 서버의 도구를 LangGraph MCP 프로토콜로 노출합니다
                    </div>
                  </div>
                  <Switch checked={detail.published} onChange={() => void togglePublish(detail.id)} />
                </div>
                {detail.published ? (
                  <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Tag color="green">public</Tag>
                    <code
                      style={{
                        fontFamily: 'var(--font-family-code)',
                        fontSize: 12,
                        color: 'var(--color-text-secondary)',
                        flex: 1,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      {detail.endpoint}
                    </code>
                    <Button
                      type="text"
                      size="small"
                      icon={<Icon name="copy" />}
                      onClick={() => {
                        if (navigator.clipboard && detail.endpoint) navigator.clipboard.writeText(detail.endpoint)
                      }}
                    />
                  </div>
                ) : null}
              </div>
            ) : null}
            {cat === 'mcp' && detail.source === 'external' ? (
              <div style={{ marginTop: 18 }}>
                <Alert type="info" showIcon message="외부 MCP — 다른 곳에서 호스팅·공개한 서버의 도구를 소비합니다." />
              </div>
            ) : null}
            {detail.body ? (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 6 }}>정의</div>
                <pre
                  style={{
                    fontFamily: 'var(--font-family-code)',
                    fontSize: 12,
                    lineHeight: 1.6,
                    color: 'var(--color-text)',
                    background: 'var(--gray-2)',
                    border: '1px solid var(--color-border-secondary)',
                    borderRadius: 8,
                    padding: '12px 14px',
                    margin: 0,
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {detail.body}
                </pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </Drawer>
      <McpForm form={mcpForm} onCancel={() => setMcpForm(null)} onSave={upsertMcp} />
      <PersonaForm form={personaForm} onCancel={() => setPersonaForm(null)} onSave={savePersona} />
    </Page>
  )
}
