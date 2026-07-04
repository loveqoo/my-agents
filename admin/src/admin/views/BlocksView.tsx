/* my-agents admin — Building blocks (재료) browser: personas, memory policies,
   MCP servers. Category tabs → list → detail drawer. */
import { useState, useEffect } from 'react'
import { Tag, Button, Tabs, Switch, Modal, Input, Select, Checkbox, Tooltip, Alert, Grid, message } from 'antd'
import { Page, DataTable, Drawer, Desc, OwnerTag, type Column } from '../shared'
import { validateName, NAME_HINT } from '../naming'
import { Icon } from '../icons'
import { MCP_STATUS, VECTOR_STATUS, type BlockItem, type BlockCategory, type StatusMeta } from '../mockData'
import {
  getBlocks,
  createMcp,
  updateMcp,
  deleteMcp,
  publishMcp,
  discoverMcpTools,
  rediscoverMcp,
  type McpToolInfo,
  type McpToolParam,
  createBlockItem,
  updateBlockItem,
  deleteBlockItem,
  listPersonaAgents,
  applyPersona,
  type PersonaUsageAgent,
} from '../../api'

const { TextArea } = Input

/* status는 백엔드에서 자유 문자열(enum 아님)이라 맵에 없는 값이 올 수 있다.
   매핑이 없으면 크래시 대신 원본 문자열을 default Tag로 폴백 렌더. */
function statusTag(map: Record<string, StatusMeta>, status?: string | null) {
  const s = status ? map[status] : undefined
  if (s) return <Tag color={s.tag}>{s.label}</Tag>
  return <Tag color="default">{status ?? '—'}</Tag>
}

/* 백엔드 McpServerIn payload — snake_case로 in. */
interface McpServerIn {
  name: string // 식별 이름(규칙, 스펙 148)
  alias?: string | null // 별명(자유 표기, 스펙 148)
  source: string
  transport: string
  url?: string
  endpoint?: string
  tools: string[]
  enabled_tools: string[]
  tools_meta?: Record<string, unknown> | null // 도구 메타(스펙 151) — null=미변경
  status: string
  published: boolean
  auth?: string
  id?: string
  owner_id?: string | null  // 소유자(스펙 112)
  can_manage?: boolean  // 관리 가능(스펙 114) — false면 편집/삭제 숨김
}

/* 비-MCP 카테고리 → 백엔드 resource 경로 매핑.
   embedding은 더 이상 여기 없다 — /vector-tables 엔드포인트가 제거되고
   "RAG 컬렉션" 전용 뷰(스펙 036)로 이관됐다. CollectionsView 참고. */
const RESOURCE_BY_CAT: Record<string, string> = {
  persona: 'personas',
  memory: 'memory-types',
}

type McpFormState = {
  mode: 'register' | 'edit'
  source?: string
  item?: BlockItem
}

type McpFormData = {
  id?: string
  name: string // 식별 이름(규칙, 스펙 148)
  alias: string // 별명(자유 표기, 스펙 148)
  transport: string
  url: string
  authMode: 'none' | 'bearer'
  auth: string // Bearer 토큰(평문 입력) 또는 편집 시 마스킹 sentinel(보존)
  tools: string[]
  enabledTools: string[]
  toolsDetail?: McpToolInfo[] // 탐색 결과 메타(스펙 151) — 저장 시 tools_meta로
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
  const blank: McpFormData = { name: '', alias: '', transport: external ? 'http' : 'stdio', url: '', authMode: 'none', auth: '', tools: [], enabledTools: [] }
  const [f, setF] = useState<McpFormData>(blank)
  const [discovering, setDiscovering] = useState(false)
  const [discoverMsg, setDiscoverMsg] = useState<{ ok: boolean; text: string } | null>(null)
  useEffect(() => {
    if (!form) return
    setDiscoverMsg(null)
    if (form.mode === 'edit' && form.item) {
      const m = form.item
      setF({
        id: m.id,
        name: m.name,
        alias: m.alias ?? '',
        transport: m.transport || 'stdio',
        url: m.url || '',
        // GET는 토큰을 마스킹(••••)으로 반환 → 존재 시 bearer, sentinel 유지(미수정 저장=보존).
        authMode: m.auth && m.auth.includes('•') ? 'bearer' : 'none',
        auth: m.auth && m.auth.includes('•') ? m.auth : '',
        tools: [...(m.tools || [])],
        enabledTools: [...(m.enabledTools || m.tools || [])],
        // 도구별 메타(설명·파라미터·승인 정책, 스펙 177)를 편집 상태로 로드 — 저장 시 tools_meta로 되씀.
        toolsDetail: m.toolsMeta
          ? Object.entries(m.toolsMeta as Record<string, { description?: string; params?: McpToolParam[]; approval?: { required?: boolean } }>).map(
              ([name, v]) => ({ name, description: v?.description ?? '', params: v?.params ?? [], approval: v?.approval }),
            )
          : [],
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
  // 도구별 "승인 필요" 토글(스펙 177 P1) — toolsDetail[t].approval.required를 켜고 끈다(저장 시 tools_meta로).
  const toggleApproval = (t: string) =>
    setF((s) => {
      const detail = s.toolsDetail ?? []
      const idx = detail.findIndex((d) => d.name === t)
      const cur = idx >= 0 ? detail[idx] : { name: t }
      const on = !cur.approval?.required
      const next = { ...cur, approval: on ? { required: true } : undefined }
      return { ...s, toolsDetail: idx >= 0 ? detail.map((d, i) => (i === idx ? next : d)) : [...detail, next] }
    })
  const isExternal = external
  const isEdit = form.mode === 'edit'
  // 라이브 탐색은 http URL이 있는 외부 MCP에서만(로컬은 자체 운영 — 도구를 운영자가 안다, stdio는 유예).
  const canDiscover = isExternal

  // 저장 전 서버에 실제로 붙어 도구목록을 가져와 자동채움(스펙 054 E). 부작용 0(list만).
  const runDiscover = async () => {
    const url = (f.url || '').trim()
    if (!url) {
      message.warning('탐색할 MCP URL을 입력하세요')
      return
    }
    setDiscovering(true)
    setDiscoverMsg(null)
    try {
      const r = await discoverMcpTools({ url, transport: 'http', auth: f.authMode === 'bearer' ? f.auth : undefined })
      if (r.ok) {
        setF((s) => ({ ...s, tools: r.tools, enabledTools: r.tools, toolsDetail: r.toolsDetail ?? [] }))
        setDiscoverMsg({ ok: true, text: `${r.detail} · ${r.latencyMs}ms` })
      } else {
        setDiscoverMsg({ ok: false, text: r.detail || '연결 실패' })
      }
    } catch {
      // 4xx(SSRF 차단) 또는 네트워크 오류 — 상세는 노출 안 함.
      setDiscoverMsg({ ok: false, text: '연결 실패 — 차단되었거나 도달할 수 없는 주소입니다.' })
    } finally {
      setDiscovering(false)
    }
  }

  const submit = () => {
    const nameErr = validateName(f.name.trim()) // 식별 이름 규칙(스펙 148)
    if (nameErr) {
      message.warning(nameErr)
      return
    }
    const id = isEdit ? f.id! : 'mcp-' + Date.now()
    const discovered = f.tools.length > 0
    const tools =
      isEdit || discovered ? f.tools : (f.toolsText || '').split(',').map((x) => x.trim()).filter(Boolean)
    const enabledTools = isEdit || discovered ? f.enabledTools : tools
    const item: BlockItem = {
      id,
      name: f.name.trim(),
      alias: f.alias.trim() || null,
      // source(유래)는 생성 후 불변(스펙 152) — 편집 시 원본 보존(custom도 그대로). 신규만 external/local.
      source: isEdit ? (form.item?.source ?? 'local') : (isExternal ? 'external' : 'local'),
      transport: f.transport,
      tools,
      enabledTools,
      usedBy: isEdit ? f.usedBy ?? 0 : 0,
      status: 'connected',
      updated: 'just now',
      published: isEdit ? !!f.published : false,
      // 도구 메타(스펙 151): 이번 폼에서 탐색했으면 그 결과로, 아니면 기존 스냅샷 보존
      toolsMeta: f.toolsDetail && f.toolsDetail.length
        ? Object.fromEntries(
            f.toolsDetail.map((d) => [
              d.name,
              {
                description: d.description ?? '',
                params: d.params ?? [],
                // 승인 정책(스펙 177) — required=true만 실어 보냄(백엔드 검증기가 동일 정규화).
                ...(d.approval?.required ? { approval: { required: true } } : {}),
              },
            ]),
          )
        : (isEdit ? form.item?.toolsMeta ?? null : null),
      url: isExternal ? (f.url || 'mcp://remote/endpoint') : undefined,
      // bearer면 토큰(평문 또는 마스킹 sentinel=보존), 없음이면 빈 문자열=제거. 로컬은 미전송.
      auth: isExternal ? (f.authMode === 'bearer' ? f.auth : '') : undefined,
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
              ? '다른 곳에서 프로토콜로 공개한 MCP 서버에 연결해, 그 도구를 가져와 씁니다.'
              : '직접 운영하는 서버를 등록합니다. 나중에 MCP로 외부 공개할 수 있습니다.'
          }
        />
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>식별 이름</span>
          <Input
            placeholder={isExternal ? '예: partner-crm' : '예: tavily'}
            value={f.name}
            status={f.name.trim() && validateName(f.name.trim()) ? 'error' : undefined}
            onChange={(e) => set('name', e.target.value)}
          />
          <span style={{ fontSize: 12, color: f.name.trim() && validateName(f.name.trim()) ? 'var(--red-6)' : 'var(--color-text-tertiary)' }}>
            {(f.name.trim() && validateName(f.name.trim())) || NAME_HINT}
          </span>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>
            별명 <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(선택 — 화면 표시용 자유 표기)</span>
          </span>
          <Input placeholder="예: 파트너 CRM" value={f.alias} onChange={(e) => set('alias', e.target.value)} />
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
                value={f.authMode}
                onChange={(v) => setF((s) => ({ ...s, authMode: v, auth: v === 'none' ? '' : s.auth }))}
                style={{ width: '100%' }}
                options={[
                  { label: '없음', value: 'none' },
                  { label: 'Bearer 토큰', value: 'bearer' },
                ]}
              />
            </label>
            {f.authMode === 'bearer' && (
              <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{ fontSize: 14, fontWeight: 500 }}>Bearer 토큰</span>
                <Input.Password
                  placeholder={f.auth.includes('•') ? '저장된 토큰 유지 — 변경하려면 새로 입력' : 'sk-... (저장 시 암호화)'}
                  value={f.auth}
                  onChange={(e) => set('auth', e.target.value)}
                  autoComplete="new-password"
                />
                <span style={{ fontSize: 12, color: 'var(--gray-7)' }}>
                  토큰은 암호화되어 저장되며, 화면에 원문이 다시 표시되지 않습니다.
                </span>
              </label>
            )}
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
        {isEdit || canDiscover ? (
          /* 활성 도구 — 외부 MCP는 "연결 테스트"로 서버에서 라이브 자동채움(스펙 054 E). */
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 14, fontWeight: 500 }}>활성 도구</span>
              {canDiscover && (
                <Button size="small" loading={discovering} onClick={runDiscover}>
                  연결 테스트
                </Button>
              )}
            </div>
            {discoverMsg && (
              <Alert
                type={discoverMsg.ok ? 'success' : 'error'}
                showIcon
                style={{ padding: '4px 12px', marginBottom: 0 }}
                message={discoverMsg.text}
              />
            )}
            {f.tools.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {f.tools.map((t) => {
                  const detail = f.toolsDetail?.find((d) => d.name === t)
                  return (
                    <div
                      key={t}
                      style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '2px 0' }}
                    >
                      <Checkbox checked={f.enabledTools.includes(t)} onChange={() => toggleTool(t)}>
                        {t}
                      </Checkbox>
                      <Tooltip title="켜면 이 도구를 호출하기 전에 승인을 받습니다(스펙 177)">
                        <Checkbox checked={!!detail?.approval?.required} onChange={() => toggleApproval(t)}>
                          <span style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>승인 필요</span>
                        </Checkbox>
                      </Tooltip>
                    </div>
                  )
                })}
              </div>
            ) : (
              <span style={{ color: 'var(--color-text-tertiary)', fontSize: 13 }}>
                {canDiscover
                  ? '“연결 테스트”를 눌러 서버의 도구를 자동으로 가져옵니다.'
                  : '등록된 도구가 없습니다.'}
              </span>
            )}
          </div>
        ) : (
          /* stdio 등 라이브 탐색 불가 transport(로컬 자체 운영): 수기 입력. */
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>
              도구{' '}
              <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(쉼표로 구분)</span>
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

/* 미리 정의된 톤 프리셋(기본 10종). tags 모드라 자유 입력도 가능. */
const TONE_PRESETS = [
  '친근함',
  '격식체',
  '간결함',
  '정중함',
  '유머러스',
  '전문적',
  '공감적',
  '단호함',
  '열정적',
  '차분함',
]

/* "친근함, 격식체" ↔ ['친근함','격식체'] 변환. tone 컬럼은 쉼표 조인 문자열로 저장. */
const splitTones = (tone: string | null | undefined): string[] =>
  (tone ?? '')
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean)
const joinTones = (tones: string[]): string => tones.map((t) => t.trim()).filter(Boolean).join(', ')

function PersonaForm({
  form,
  onCancel,
  onSave,
}: {
  form: PersonaFormState | null
  onCancel: () => void
  onSave: (data: { id?: string; name: string; alias: string; tone: string; body: string }) => void
}) {
  const [name, setName] = useState('')
  const [alias, setAlias] = useState('')
  const [tones, setTones] = useState<string[]>([])
  const [body, setBody] = useState('')
  // 이 페르소나를 쓰는 에이전트(스펙 161) — 편집 모드에서만 로드·표시.
  const [usage, setUsage] = useState<PersonaUsageAgent[]>([])
  const [usageLoading, setUsageLoading] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [applying, setApplying] = useState(false)
  useEffect(() => {
    if (!form) return
    if (form.mode === 'edit' && form.item) {
      setName(form.item.name ?? '')
      setAlias(form.item.alias ?? '')
      setTones(splitTones(form.item.tone))
      setBody(form.item.body ?? '')
    } else {
      setName('')
      setAlias('')
      setTones([])
      setBody('')
    }
  }, [form])
  // 편집 대상 페르소나 id 기준으로 사용 에이전트 목록 로드. 기본 선택 = stale && canManage.
  const loadUsage = async (id: string) => {
    setUsageLoading(true)
    try {
      const list = await listPersonaAgents(id)
      setUsage(list)
      setSelected(list.filter((u) => u.stale && u.canManage).map((u) => u.id))
    } catch (e) {
      message.error(e instanceof Error ? e.message : '사용 에이전트 목록을 불러오지 못했습니다')
    } finally {
      setUsageLoading(false)
    }
  }
  useEffect(() => {
    if (form && form.mode === 'edit' && form.item?.id) {
      void loadUsage(form.item.id)
    } else {
      setUsage([])
      setSelected([])
    }
  }, [form])
  if (!form) return null
  const isEdit = form.mode === 'edit'
  const submit = () => {
    const nameErr = validateName(name.trim()) // 식별 이름 규칙(스펙 148)
    if (nameErr) {
      message.warning(nameErr)
      return
    }
    onSave({ id: isEdit ? form.item?.id : undefined, name: name.trim(), alias: alias.trim(), tone: joinTones(tones), body })
  }
  const staleCount = usage.filter((u) => u.stale).length
  const applySelected = async () => {
    if (!form.item?.id || selected.length === 0) return
    setApplying(true)
    try {
      const result = await applyPersona(form.item.id, selected)
      await loadUsage(form.item.id)
      message.success(`${result.applied.length}개 반영, ${result.skipped.length}개 건너뜀`)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '반영에 실패했습니다')
    } finally {
      setApplying(false)
    }
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
          <span style={{ fontSize: 14, fontWeight: 500 }}>식별 이름</span>
          <Input
            placeholder="예: 친절한-고양이"
            value={name}
            status={name.trim() && validateName(name.trim()) ? 'error' : undefined}
            onChange={(e) => setName(e.target.value)}
          />
          <span style={{ fontSize: 12, color: name.trim() && validateName(name.trim()) ? 'var(--red-6)' : 'var(--color-text-tertiary)' }}>
            {(name.trim() && validateName(name.trim())) || NAME_HINT}
          </span>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>
            별명 <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(선택 — 화면 표시용 자유 표기)</span>
          </span>
          <Input placeholder="예: 친절한 고양이" value={alias} onChange={(e) => setAlias(e.target.value)} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>
            톤 <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(선택 · 미리 정의된 톤 선택 또는 직접 입력 후 Enter)</span>
          </span>
          <Select
            mode="tags"
            allowClear
            placeholder="예: 친근함, 격식체 — 목록에서 고르거나 직접 입력"
            value={tones}
            onChange={(v: string[]) => setTones(v)}
            options={TONE_PRESETS.map((t) => ({ label: t, value: t }))}
            tokenSeparators={[',']}
          />
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
        {isEdit ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, borderTop: '1px solid var(--color-border-secondary)', paddingTop: 12 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>이 페르소나를 쓰는 에이전트</span>
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              이 페르소나 사용 {usage.length}개 · 오래됨 {staleCount}개
            </span>
            {usageLoading ? (
              <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>불러오는 중…</span>
            ) : usage.length ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {usage.map((u) => (
                  <div key={u.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Checkbox
                      checked={selected.includes(u.id)}
                      disabled={!u.canManage}
                      onChange={(e) =>
                        setSelected((s) => (e.target.checked ? [...s, u.id] : s.filter((id) => id !== u.id)))
                      }
                    >
                      {u.alias ?? u.name}
                    </Checkbox>
                    {u.stale ? <Tag color="warning">오래됨</Tag> : null}
                    {!u.canManage ? (
                      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>권한 없음</span>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>이 페르소나를 쓰는 에이전트가 없습니다</span>
            )}
            <Button size="small" loading={applying} disabled={selected.length === 0} onClick={applySelected} style={{ alignSelf: 'flex-start' }}>
              선택 에이전트에 반영
            </Button>
          </div>
        ) : null}
      </div>
    </Modal>
  )
}

/* ---- memory / embedding 공용 작성·편집 폼 (필드 스펙 기반) ---- */
type BlockField =
  | { kind: 'text'; key: string; label: string; required?: boolean; placeholder?: string; hint?: string }
  | { kind: 'number'; key: string; label: string; placeholder?: string; hint?: string }
  | { kind: 'select'; key: string; label: string; options: { label: string; value: string }[]; hint?: string }
  | { kind: 'textarea'; key: string; label: string; rows?: number; placeholder?: string; hint?: string }

/* preserve: 폼에 노출하지 않지만 PUT(전체 교체) 시 기존 값을 유지해야 하는 필드.
   누락하면 백엔드 *In 스키마 기본값으로 덮어써져 데이터가 날아간다. */
type BlockFormConfig = { resource: string; title: string; intro: string; fields: BlockField[]; preserve?: string[] }

/* memory는 의도적으로 제외 — 시스템 정의 enum(런타임이 이름 문자열에 의존)이라
   빌딩 블록에서 읽기 전용으로 다룬다. (spec 016) 권한(permission) 카테고리는 스펙 177 P3에서 제거 —
   현재 공용 폼 카테고리 없음(향후 카테고리 추가 시 이 자리에). */
const BLOCK_FORMS: Record<string, BlockFormConfig> = {}

type BlockFormState = { cat: string; mode: 'create' | 'edit'; item?: BlockItem }

function BlockForm({
  form,
  onCancel,
  onSave,
}: {
  form: BlockFormState | null
  onCancel: () => void
  onSave: (resource: string, id: string | undefined, payload: Record<string, unknown>) => void
}) {
  const cfg = form ? BLOCK_FORMS[form.cat] : null
  const [values, setValues] = useState<Record<string, string>>({})
  useEffect(() => {
    if (!form || !cfg) return
    const next: Record<string, string> = {}
    for (const fld of cfg.fields) {
      const raw =
        form.mode === 'edit' && form.item
          ? (form.item as unknown as Record<string, unknown>)[fld.key]
          : undefined
      next[fld.key] =
        raw == null ? (fld.kind === 'select' ? (fld.options[0]?.value ?? '') : '') : String(raw)
    }
    setValues(next)
  }, [form])
  if (!form || !cfg) return null
  const isEdit = form.mode === 'edit'
  const set = (k: string, v: string) => setValues((prev) => ({ ...prev, [k]: v }))
  const submit = () => {
    for (const fld of cfg.fields) {
      if (fld.kind === 'text' && fld.required && !values[fld.key]?.trim()) {
        message.warning(`${fld.label}을(를) 입력하세요`)
        return
      }
    }
    // 식별 이름 규칙(스펙 148) — name 필드가 있으면 프론트에서도 즉시 검사(진실원은 서버 400)
    if ('name' in values) {
      const nameErr = validateName((values.name ?? '').trim())
      if (nameErr) {
        message.warning(nameErr)
        return
      }
    }
    const payload: Record<string, unknown> = {}
    for (const fld of cfg.fields) {
      const v = values[fld.key] ?? ''
      if (fld.kind === 'number') payload[fld.key] = v.trim() === '' ? null : Number(v)
      else if (fld.kind === 'text' && !fld.required) payload[fld.key] = v.trim() === '' ? null : v.trim()
      else payload[fld.key] = fld.kind === 'textarea' ? v : v.trim()
    }
    /* 편집 시: 폼에 없는 동기화 관리 필드(rows·status 등)를 기존 값으로 보존.
       PUT은 전체 교체라 누락하면 스키마 기본값으로 덮어써진다. */
    if (isEdit && form.item) {
      const item = form.item as unknown as Record<string, unknown>
      for (const k of cfg.preserve ?? []) {
        if (item[k] != null) payload[k] = item[k]
      }
    }
    onSave(cfg.resource, isEdit ? form.item?.id : undefined, payload)
  }
  return (
    <Modal
      open={!!form}
      width={560}
      title={isEdit ? `${cfg.title} 편집 · ${form.item?.name ?? ''}` : `새 ${cfg.title}`}
      okText={isEdit ? '저장' : '등록'}
      cancelText="취소"
      onCancel={onCancel}
      onOk={submit}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '64vh', overflow: 'auto' }}>
        <Alert type="info" showIcon style={{ marginBottom: 0 }} message={cfg.intro} />
        {cfg.fields.map((fld) => (
          <label key={fld.key} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>
              {fld.label}
              {!('required' in fld && fld.required) ? (
                <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}> (선택)</span>
              ) : null}
              {fld.hint ? (
                <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}> · {fld.hint}</span>
              ) : null}
            </span>
            {fld.kind === 'textarea' ? (
              <TextArea
                rows={fld.rows ?? 4}
                placeholder={fld.placeholder}
                value={values[fld.key] ?? ''}
                onChange={(e) => set(fld.key, e.target.value)}
              />
            ) : fld.kind === 'select' ? (
              <Select
                value={values[fld.key] ?? fld.options[0]?.value}
                onChange={(v: string) => set(fld.key, v)}
                options={fld.options}
              />
            ) : (
              <Input
                type={fld.kind === 'number' ? 'number' : 'text'}
                placeholder={fld.placeholder}
                value={values[fld.key] ?? ''}
                onChange={(e) => set(fld.key, e.target.value)}
              />
            )}
          </label>
        ))}
      </div>
    </Modal>
  )
}

export default function BlocksView() {
  const isMobileTabs = !Grid.useBreakpoint().md // 모바일 탭 축소(스펙 133)
  const [data, setData] = useState<Record<string, BlockCategory>>({})
  const [cat, setCat] = useState('persona')
  const [detail, setDetail] = useState<BlockItem | null>(null)
  const [mcpForm, setMcpForm] = useState<McpFormState | null>(null) // { mode:'register'|'edit', item? }
  const [personaForm, setPersonaForm] = useState<PersonaFormState | null>(null)
  const [blockForm, setBlockForm] = useState<BlockFormState | null>(null)

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
      const raw = await getBlocks()
      // embedding 카테고리는 RAG 컬렉션 전용 뷰(스펙 036)로 이관 — /vector-tables CRUD가
      // 제거됐으므로 빌딩 블록에서는 탭째 숨긴다. 남으면 깨진 엔드포인트를 호출하게 된다.
      const { embedding: _embedding, ...next } = raw
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

  const [rediscovering, setRediscovering] = useState(false)
  // 도구 정보 재탐색(스펙 151) — 자격증명은 백엔드가 복호. 갱신 후 목록 재로드(드로어는 id로 재조회).
  const runRediscover = async (id: string) => {
    setRediscovering(true)
    try {
      await rediscoverMcp(id)
      await loadBlocks()
      message.success('도구 정보를 새로 탐색했습니다')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '재탐색에 실패했습니다')
    } finally {
      setRediscovering(false)
    }
  }

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
      alias: item.alias ?? null,
      source: item.source ?? 'local',
      transport: item.transport ?? 'stdio',
      url: item.url,
      endpoint: item.endpoint,
      tools: item.tools ?? [],
      enabled_tools: item.enabledTools ?? [],
      tools_meta: (item.toolsMeta as Record<string, unknown> | null) ?? null, // null=백엔드 미변경(스펙 151)
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

  const createCurrent = () => {
    /* 카테고리별 전용 폼 오픈. persona·mcp는 자체 폼, 나머지는 BLOCK_FORMS 공용 폼. */
    if (cat === 'persona') {
      setPersonaForm({ mode: 'create' })
      return
    }
    if (BLOCK_FORMS[cat]) {
      setBlockForm({ cat, mode: 'create' })
      return
    }
  }

  const savePersona = async (data: { id?: string; name: string; alias: string; tone: string; body: string }) => {
    const payload = { name: data.name, alias: data.alias || null, tone: data.tone || null, body: data.body }
    try {
      if (data.id) await updateBlockItem('personas', data.id, payload)
      else await createBlockItem('personas', payload)
      await loadBlocks()
      setPersonaForm(null)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '페르소나 저장에 실패했습니다')
    }
  }

  const saveBlock = async (resource: string, id: string | undefined, payload: Record<string, unknown>) => {
    try {
      if (id) await updateBlockItem(resource, id, payload)
      else await createBlockItem(resource, payload)
      await loadBlocks()
      setBlockForm(null)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '저장에 실패했습니다')
    }
  }

  const colsFor = (key: string): Column<BlockItem>[] => {
    if (key === 'mcp')
      return [
        {
          key: 'name',
          title: '서버',
          render: (r) => (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <code style={{ fontFamily: 'var(--font-family-code)', color: 'var(--cyan-7)', fontSize: 13 }}>{r.name}</code>
              {r.alias ? <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{r.alias}</span> : null}
              {r.source === 'external' ? <Tag color="purple">외부</Tag> : r.source === 'custom' ? <Tag color="cyan">커스텀</Tag> : <Tag>로컬</Tag>}
              <OwnerTag ownerId={r.owner_id} canManage={r.can_manage} />
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
          render: (r) => statusTag(MCP_STATUS, r.status),
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
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <code style={{ fontFamily: 'var(--font-family-code)', color: 'var(--cyan-7)', fontSize: 13 }}>{r.name}</code>
              {r.alias ? <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{r.alias}</span> : null}
            </span>
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
          render: (r) => statusTag(VECTOR_STATUS, r.status),
        },
        {
          key: 'usedBy',
          title: '사용',
          width: 70,
          align: 'right',
          render: (r) => <span style={{ color: 'var(--color-text-secondary)' }}>{r.usedBy}</span>,
        },
      ]
    // persona + memory
    return [
      {
        key: 'name',
        title: (def?.label ?? '').replace(/s$/, ''),
        render: (r) => (
          <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 500, color: 'var(--color-text-heading)' }}>{r.alias || r.name}</span>
            {r.alias ? (
              <code style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>{r.name}</code>
            ) : null}
          </span>
        ),
      },
      {
        key: 'meta',
        title: key === 'persona' ? '톤' : '범위',
        width: 200,
        render: (r) =>
          key === 'persona' ? (
            splitTones(r.tone).length ? (
              <span>
                {splitTones(r.tone).map((t) => (
                  <Tag key={t} color="magenta">
                    {t}
                  </Tag>
                ))}
              </span>
            ) : (
              <span style={{ color: 'var(--color-text-tertiary)' }}>—</span>
            )
          ) : (
            <Tag color="purple">{r.scope}</Tag>
          ),
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
          <span style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            <Button icon={<Icon name="global" />} onClick={() => setMcpForm({ mode: 'register', source: 'external' })}>
              외부 등록
            </Button>
            <Button type="primary" icon={<Icon name="plus" />} onClick={() => setMcpForm({ mode: 'register', source: 'local' })}>
              새 서버
            </Button>
          </span>
        ) : cat === 'memory' ? null : (
          <Button type="primary" icon={<Icon name="plus" />} onClick={createCurrent}>
            새 항목
          </Button>
        )
      }
    >
      {/* 모바일(스펙 133 점검): 기본 크기·간격이면 셋째 탭이 반쯤 잘림 — size small+간격 축소로
          390px에 세 탭이 온전히 들어오게. 데스크톱은 기존 그대로. */}
      <Tabs
        activeKey={cat}
        onChange={(k) => {
          setCat(k)
          setDetail(null)
        }}
        items={tabItems}
        size={isMobileTabs ? 'small' : undefined}
        tabBarGutter={isMobileTabs ? 14 : undefined}
      />
      <div style={{ marginTop: 4, marginBottom: 14, color: 'var(--color-text-tertiary)', fontSize: 14 }}>{def?.desc}</div>
      <DataTable columns={colsFor(cat)} rows={def?.items ?? []} onRowClick={setDetail} />

      <Drawer
        open={!!detail}
        title={detail ? detail.name : ''}
        width={440}
        onClose={() => setDetail(null)}
        footer={
          cat === 'memory' ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--color-text-tertiary)', fontSize: 13 }}>
              <Icon name="lock" /> 시스템 정의 메모리 타입 — 읽기 전용
            </span>
          ) : cat === 'mcp' && detail?.can_manage === false ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--color-text-tertiary)', fontSize: 13 }}>
              <Icon name="lock" /> 다른 사용자 소유 — 관리 권한 없음
            </span>
          ) : (
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
            ) : BLOCK_FORMS[cat] ? (
              <Button
                type="primary"
                icon={<Icon name="edit" />}
                onClick={() => detail && setBlockForm({ cat, mode: 'edit', item: detail })}
              >
                편집
              </Button>
            ) : (
              <Button type="primary" icon={<Icon name="edit" />} disabled>
                편집
              </Button>
            )}
          </>
          )
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
            {cat === 'embedding' && detail.status ? (
              <Desc label="상태">{statusTag(VECTOR_STATUS, detail.status)}</Desc>
            ) : null}
            {splitTones(detail.tone).length ? (
              <Desc label="톤">
                {splitTones(detail.tone).map((t) => (
                  <Tag key={t} color="magenta">
                    {t}
                  </Tag>
                ))}
              </Desc>
            ) : null}
            {detail.scope ? (
              <Desc label="범위">{cat === 'memory' ? <Tag color="purple">{detail.scope}</Tag> : <Tag>{detail.scope}</Tag>}</Desc>
            ) : null}
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
            {cat === 'mcp' && detail.tools ? (
              /* 도구 카드(스펙 151) — 이름·활성·설명·파라미터 표. 메타 없는 기존 행은 이름만(grandfather). */
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)' }}>
                    도구 {detail.tools.length}개
                  </span>
                  {detail.transport === 'http' && detail.url && detail.can_manage !== false ? (
                    <Button
                      size="small"
                      icon={<Icon name="reload" />}
                      loading={rediscovering}
                      onClick={() => void runRediscover(detail.id)}
                    >
                      도구 정보 새로 탐색
                    </Button>
                  ) : null}
                </div>
                {detail.tools.map((t) => {
                  const enabled = (detail.enabledTools || detail.tools || []).includes(t)
                  const meta = detail.toolsMeta?.[t]
                  return (
                    <div
                      key={t}
                      style={{
                        padding: '10px 12px',
                        border: '1px solid var(--color-border-secondary)',
                        borderRadius: 'var(--radius-lg)',
                        background: 'var(--gray-2)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 6,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13, color: 'var(--cyan-7)', fontWeight: 600 }}>
                          {t}
                        </code>
                        {enabled ? <Tag color="geekblue" style={{ margin: 0 }}>활성</Tag> : <Tag style={{ margin: 0 }}>비활성</Tag>}
                      </div>
                      {meta?.description ? (
                        <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>{meta.description}</div>
                      ) : null}
                      {Array.isArray(meta?.params) && meta.params.length > 0 ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                          {meta.params.map((p) => (
                            <div key={p.name} style={{ display: 'flex', gap: 8, fontSize: 12, alignItems: 'baseline' }}>
                              <code style={{ fontFamily: 'var(--font-family-code)', color: 'var(--color-text-heading)' }}>{p.name}</code>
                              <span style={{ color: 'var(--color-text-tertiary)' }}>{p.type ?? 'any'}</span>
                              {p.required ? <Tag color="orange" style={{ margin: 0, fontSize: 11 }}>필수</Tag> : null}
                            </div>
                          ))}
                        </div>
                      ) : meta ? (
                        <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>파라미터 없음</div>
                      ) : (
                        <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                          상세 정보 없음 — [도구 정보 새로 탐색]으로 채울 수 있습니다.
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : detail.tools ? (
              <Desc label="도구">
                <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
                  {detail.tools.map((t) => (
                    <Tag key={t}>{t}</Tag>
                  ))}
                </span>
              </Desc>
            ) : null}
            {cat === 'mcp' && detail.status ? <Desc label="상태">{statusTag(MCP_STATUS, detail.status)}</Desc> : null}
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
                  <Switch checked={detail.published} disabled={detail.can_manage === false} onChange={() => void togglePublish(detail.id)} />
                </div>
                {/* 서빙 URL(스펙 156): custom은 실제 서빙 URL(served_url), 그 외는 기존 endpoint. */}
                {(() => {
                  const url = detail.served_url ?? detail.endpoint
                  return detail.published && url ? (
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
                        {url}
                      </code>
                      <Button
                        type="text"
                        size="small"
                        icon={<Icon name="copy" />}
                        onClick={() => {
                          if (navigator.clipboard && url) navigator.clipboard.writeText(url)
                        }}
                      />
                    </div>
                  ) : null
                })()}
                {/* custom 미공개 안내(스펙 156): 켜면 이 URL로 외부에 서빙된다. */}
                {!detail.published && detail.served_url ? (
                  <div style={{ marginTop: 12, fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                    공개하면 외부가 이 URL로 등록·접속합니다: <code style={{ fontFamily: 'var(--font-family-code)' }}>{detail.served_url}</code>
                  </div>
                ) : null}
              </div>
            ) : null}
            {cat === 'mcp' && detail.source === 'external' ? (
              <div style={{ marginTop: 18 }}>
                <Alert type="info" showIcon message="외부 MCP — 다른 곳에서 호스팅·공개한 서버의 도구를 가져와 씁니다." />
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
      <BlockForm form={blockForm} onCancel={() => setBlockForm(null)} onSave={saveBlock} />
    </Page>
  )
}
