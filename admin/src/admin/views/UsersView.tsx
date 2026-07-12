/* my-agents admin — Users view (스펙 031): 유저·역할 관리(admin 보호).
   목록 + 활성 토글 + 역할 부여/회수 + 유저 추가 모달. 공개 등록은 없으므로 생성은 여기서만.
   백엔드: GET/POST /admin/users, PATCH active, GET /admin/roles, POST/DELETE roles. */
import { useState, useEffect, useCallback, type ReactNode } from 'react'
import { Tag, Button, Modal, Input, Switch, Select, Form, message, Tooltip, Space, Tabs } from 'antd'
import { Page, DataTable, type Column } from '../shared'
import {
  listUsers,
  createUser,
  setUserActive,
  listRoles,
  grantRole,
  revokeRole,
  listPolicies,
  grantPolicy,
  revokePolicy,
  listMcpServers,
  listCollections,
  listAgents,
  type AdminUser,
  type RoleInfo,
  type Policy,
  type McpServerLite,
  type Collection,
  type Agent,
} from '../../api'
import { runWithToast } from '../../hooks'

const ROLE_COLOR: Record<string, string> = { admin: 'volcano', member: 'blue' }

/* 권한 종류 메타(스펙 200) — 코드 kind를 사람 말로. hasName=false(기억 3종)는 브로커 리소스가 내부
   고정('user')이라 kind-레벨 부여만 의미 있음(broker._cap_resource). 판정 키: mcp=서버 name ·
   rag=컬렉션 name · agent=agentId(agt_…) — Select value를 이 키와 일치시켜야 부여가 실효된다. */
const KIND_META: Record<string, { label: string; noun: string; hasName: boolean }> = {
  mcp: { label: '도구 (MCP 서버)', noun: '도구', hasName: true },
  rag: { label: '지식 (RAG 컬렉션)', noun: '지식', hasName: true },
  agent: { label: '하위 에이전트', noun: '하위 에이전트', hasName: true },
  memory: { label: '기억 검색', noun: '기억 검색', hasName: false },
  memwrite: { label: '기억 저장', noun: '기억 저장', hasName: false },
  memedit: { label: '기억 수정/삭제', noun: '기억 수정/삭제', hasName: false },
}

/* ---- 유저 추가 모달 ---- */
function CreateUserModal({
  open,
  onCancel,
  onCreated,
}: {
  open: boolean
  onCancel: () => void
  onCreated: () => void
}) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (open) form.resetFields()
  }, [open, form])

  const submit = async () => {
    const v = await form.validateFields().catch(() => null)
    if (!v) return
    setSaving(true)
    try {
      await createUser({
        email: v.email.trim(),
        password: v.password,
        display_name: v.display_name?.trim() || undefined,
        is_superuser: !!v.is_superuser,
      })
      message.success('유저를 생성했습니다')
      onCreated()
    } catch (e) {
      message.error(e instanceof Error && /409/.test(e.message) ? '이미 존재하는 이메일입니다' : '생성 실패')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="유저 추가" open={open} onCancel={onCancel} onOk={submit} confirmLoading={saving} okText="생성">
      <Form form={form} layout="vertical" requiredMark={false} style={{ marginTop: 12 }}>
        <Form.Item name="email" label="이메일" rules={[{ required: true, type: 'email', message: '이메일을 입력하세요' }]}>
          <Input placeholder="user@example.com" autoComplete="off" />
        </Form.Item>
        <Form.Item name="password" label="비밀번호" rules={[{ required: true, min: 8, message: '8자 이상' }]}>
          <Input.Password placeholder="초기 비밀번호(8자 이상)" autoComplete="new-password" />
        </Form.Item>
        <Form.Item name="display_name" label="표시 이름(선택)">
          <Input placeholder="이름" />
        </Form.Item>
        <Form.Item name="is_superuser" label="슈퍼유저" valuePropName="checked" extra="권한 검사를 우회합니다 — 신중히.">
          <Switch />
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default function UsersView() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [roles, setRoles] = useState<RoleInfo[]>([])
  const [policies, setPolicies] = useState<Policy[]>([])
  const [loading, setLoading] = useState(true)
  const [modal, setModal] = useState(false)
  // 권한 부여 카탈로그(스펙 200) — 자유입력 대신 등록된 자원에서 고르게. 실패해도 유저 목록은 떠야
  // 하므로 각자 best-effort(catch → 빈 배열, 그 종류만 옵션 없음).
  const [mcps, setMcps] = useState<McpServerLite[]>([])
  const [collections, setCollections] = useState<Collection[]>([])
  const [agents, setAgents] = useState<Agent[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [u, r, p, m, c, a] = await Promise.all([
        listUsers(),
        listRoles(),
        listPolicies(),
        listMcpServers().catch(() => [] as McpServerLite[]),
        listCollections().catch(() => [] as Collection[]),
        listAgents().catch(() => [] as Agent[]),
      ])
      setUsers(u)
      setRoles(r)
      setPolicies(p)
      setMcps(m)
      setCollections(c)
      setAgents(a)
    } catch {
      message.error('목록을 불러오지 못했습니다')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const toggleActive = async (u: AdminUser) => {
    await runWithToast(async () => {
      const updated = await setUserActive(u.id, !u.is_active)
      setUsers((xs) => xs.map((x) => (x.id === u.id ? updated : x)))
    }, { error: '상태 변경 실패' })
  }

  const onGrant = async (u: AdminUser, role: string) => {
    await runWithToast(async () => {
      const updated = await grantRole(u.id, role)
      setUsers((xs) => xs.map((x) => (x.id === u.id ? updated : x)))
    }, { error: '역할 부여 실패' })
  }

  const onRevoke = async (u: AdminUser, role: string) => {
    await runWithToast(async () => {
      const updated = await revokeRole(u.id, role)
      setUsers((xs) => xs.map((x) => (x.id === u.id ? updated : x)))
    }, { error: '역할 회수 실패' })
  }

  /* ---- 권한 부여(정책) — 스펙 177 P3 ---- */
  const subjectLabel = (subject: string): ReactNode => {
    const u = users.find((x) => x.id === subject)
    if (u) return u.email
    const r = roles.find((x) => x.name === subject)
    if (r) return <Tag color={ROLE_COLOR[r.name]}>{r.name}</Tag>
    return subject
  }

  const onRevokePolicy = async (p: Policy) => {
    const ok = await runWithToast(() => revokePolicy(p.subject, p.object, p.action), {
      success: '권한을 회수했습니다',
      error: '권한 회수 실패',
    })
    if (ok) void load()
  }

  // 대상 축 분리(스펙 200 C) — 역할(그 역할 전원) vs 특정 유저(그 사람만). 혼재 Select의 정신모델
  // 문제를 축 선택으로 해소. 전환 시 대상 초기화(다른 축 값 잔존 방지).
  const [grantTarget, setGrantTarget] = useState<'role' | 'user'>('role')
  const [grantSubject, setGrantSubject] = useState<string | undefined>(undefined)
  const [grantKind, setGrantKind] = useState<string | undefined>(undefined)
  const [grantName, setGrantName] = useState('') // ''=전체(kind-레벨). Select 값(자유입력 제거, 스펙 200 A)
  const [granting, setGranting] = useState(false)

  const kindMeta = grantKind ? KIND_META[grantKind] : undefined
  // 종류별 카탈로그 옵션 — value는 브로커 판정 키(mcp=서버 name·rag=컬렉션 name·agent=agentId),
  // label은 표시 규약(이름 단독, 스펙 210).
  const nameOptions =
    grantKind === 'mcp'
      ? mcps.map((m) => ({ value: m.name, label: m.name }))
      : grantKind === 'rag'
        ? collections.map((c) => ({ value: c.name, label: c.name }))
        : grantKind === 'agent'
          ? agents.map((a) => ({ value: a.agentId, label: a.name }))
          : []

  const grantObject = grantKind
    ? kindMeta?.hasName && grantName
      ? `capability:${grantKind}:${grantName}`
      : `capability:${grantKind}`
    : ''

  /* capability 코드 → 사람 말(스펙 200 B). 미리보기·부여 목록 공용. agent는 agt_… id를 목록에서
     이름으로 되찾아 표시(모르면 id 그대로 — 삭제된 에이전트 등). */
  const capLabel = (object: string): string => {
    if (!object.startsWith('capability:')) return object
    const body = object.slice('capability:'.length)
    const sep = body.indexOf(':')
    const kind = sep === -1 ? body : body.slice(0, sep)
    const name = sep === -1 ? '' : body.slice(sep + 1)
    const meta = KIND_META[kind]
    if (!meta) return object
    if (!name) return meta.hasName ? `모든 ${meta.noun}` : meta.noun
    if (kind === 'agent') {
      const a = agents.find((x) => x.agentId === name)
      return `${meta.noun} · ${a ? a.name : name}`
    }
    return `${meta.noun} · ${name}`
  }

  // 문장 미리보기 — "누구에게 무엇을" 을 사람이 읽는 한 문장으로.
  const subjectPhrase = grantSubject
    ? grantTarget === 'role'
      ? `'${grantSubject}' 역할`
      : `'${users.find((u) => u.id === grantSubject)?.email ?? grantSubject}' 유저`
    : ''
  const sentence =
    grantSubject && grantKind ? `${subjectPhrase}에게 ${capLabel(grantObject)} 사용을 허용합니다.` : ''

  const onGrantPolicy = async () => {
    if (!grantSubject || !grantKind) return
    setGranting(true)
    const ok = await runWithToast(
      () => grantPolicy({ subject: grantSubject, object: grantObject, action: 'invoke' }),
      { success: '권한을 부여했습니다', error: '권한 부여 실패' },
    )
    setGranting(false)
    if (ok) {
      setGrantSubject(undefined)
      setGrantKind(undefined)
      setGrantName('')
      void load()
    }
  }

  type PolicyRow = Policy & { rowKey: string }
  const policyRows: PolicyRow[] = policies
    .filter((p) => p.object.startsWith('capability:'))
    .map((p) => ({ ...p, rowKey: `${p.subject}|${p.object}|${p.action}` }))

  const policyColumns: Column<PolicyRow>[] = [
    { key: 'subject', title: '대상', render: (p) => subjectLabel(p.subject) },
    {
      key: 'object',
      title: '권한',
      // 사람 말 우선(스펙 200 B) — 코드는 툴팁으로만(감사 로그 대조·디버깅용).
      render: (p) => (
        <Tooltip title={<span style={{ fontFamily: 'var(--font-family-code)' }}>{p.object}</span>}>
          <Tag>{capLabel(p.object)}</Tag>
        </Tooltip>
      ),
    },
    {
      key: 'actions',
      title: '',
      render: (p) => (
        <Button size="small" danger onClick={() => void onRevokePolicy(p)}>
          회수
        </Button>
      ),
    },
  ]

  const columns: Column<AdminUser>[] = [
    {
      key: 'email',
      title: '유저',
      render: (u) => (
        <div>
          <div style={{ fontWeight: 500 }}>
            {u.email}
            {u.is_superuser && (
              <Tag color="gold" style={{ marginInlineStart: 8 }}>
                superuser
              </Tag>
            )}
          </div>
          {u.display_name && (
            <div style={{ color: 'var(--color-text-tertiary)', fontSize: 13 }}>{u.display_name}</div>
          )}
        </div>
      ),
    },
    {
      key: 'source',
      title: '출처',
      render: (u) => <Tag>{u.source}</Tag>,
    },
    {
      key: 'roles',
      title: '역할',
      render: (u) => {
        const assignable = roles.filter((r) => !u.roles.includes(r.name))
        return (
          <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            {u.roles.length === 0 && <span style={{ color: 'var(--color-text-tertiary)' }}>—</span>}
            {u.roles.map((r) => (
              <Tag
                key={r}
                color={ROLE_COLOR[r]}
                closable
                onClose={(e) => {
                  e.preventDefault()
                  void onRevoke(u, r)
                }}
              >
                {r}
              </Tag>
            ))}
            {assignable.length > 0 && (
              <Select<string>
                size="small"
                value={undefined}
                placeholder="+ 역할"
                style={{ minWidth: 96 }}
                options={assignable.map((r) => ({ value: r.name, label: r.name }))}
                onChange={(v) => void onGrant(u, v)}
              />
            )}
          </span>
        )
      },
    },
    {
      key: 'active',
      title: '활성',
      render: (u) => (
        <Tooltip title={u.is_active ? '비활성화' : '활성화'}>
          <Switch size="small" checked={u.is_active} onChange={() => void toggleActive(u)} />
        </Tooltip>
      ),
    },
    // "상태" 컬럼 제거(스펙 250 #3) — "활성" Switch와 같은 is_active 파생(값=상태 문법, 토글이 canonical).
  ]

  // 스펙 200 후속: 유저 목록·권한 부여 탭 분리(유저가 늘면 세로 나열이 불편 — 사용자 요청)
  const [tab, setTab] = useState<'users' | 'grants'>('users')

  /* 권한 부여 패널(스펙 177 P3 → 200 개편) — 자유입력→카탈로그 선택·코드→문장·역할/유저 축 분리·도입 문장 */
  const grantPane = (
    <div>
      <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginBottom: 16, lineHeight: 1.7 }}>
        권한이란 에이전트가 쓸 수 있는 <b>도구(MCP)</b>·<b>지식(RAG 컬렉션)</b>·<b>하위 에이전트</b>·<b>기억</b>입니다.
        관리자(admin)는 모든 권한을 쓸 수 있고, <b>일반 멤버(member)는 여기서 열어준 권한만</b> 쓸 수 있습니다(기본 잠김).
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 16 }}>
        {/* 스펙 224: [역할 기준|유저 기준]는 부여 대상(역할 전체 vs 특정 유저)이 바뀌어 폼·목록이
            달라지는 전환이라 Segmented→Tabs로 통일 — 상위 유저 목록/권한 부여 Tabs와 시각 일관(스펙 219와 동형). */}
        <div>
          <Tabs
            activeKey={grantTarget}
            onChange={(k) => {
              setGrantTarget(k as 'role' | 'user')
              setGrantSubject(undefined) // 축 전환 시 다른 축 값 잔존 방지
            }}
            items={[
              { key: 'role', label: '역할 기준' },
              { key: 'user', label: '유저 기준' },
            ]}
            style={{ marginBottom: -8 }}
          />
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            {grantTarget === 'role' ? '이 역할을 가진 모든 유저에게 적용됩니다.' : '이 유저에게만 적용됩니다.'}
          </span>
        </div>
        <Space wrap align="end">
          <div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 4 }}>
              {grantTarget === 'role' ? '역할' : '유저'}
            </div>
            <Select<string>
              style={{ minWidth: 200 }}
              placeholder={grantTarget === 'role' ? '역할 선택' : '유저 선택'}
              value={grantSubject}
              onChange={setGrantSubject}
              options={
                grantTarget === 'role'
                  ? roles.map((r) => ({ value: r.name, label: r.name }))
                  : users.map((u) => ({ value: u.id, label: u.email }))
              }
            />
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 4 }}>권한 종류</div>
            <Select<string>
              style={{ minWidth: 180 }}
              placeholder="종류 선택"
              value={grantKind}
              onChange={(v) => {
                setGrantKind(v)
                setGrantName('') // 종류가 바뀌면 카탈로그도 바뀌므로 초기화(타 종류 값 잔존 방지)
              }}
              options={Object.entries(KIND_META).map(([value, m]) => ({ value, label: m.label }))}
            />
          </div>
          {kindMeta?.hasName ? (
            <div>
              <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 4 }}>
                어느 {kindMeta.noun}?
              </div>
              <Select<string>
                style={{ minWidth: 220 }}
                value={grantName}
                onChange={setGrantName}
                options={[
                  { value: '', label: `전체 — 모든 ${kindMeta.noun}` },
                  ...nameOptions,
                ]}
                notFoundContent={`등록된 ${kindMeta.noun} 없음`}
              />
            </div>
          ) : null}
          <Button
            type="primary"
            loading={granting}
            disabled={!grantSubject || !grantKind}
            onClick={() => void onGrantPolicy()}
          >
            부여
          </Button>
        </Space>
        {sentence ? (
          <div>
            <div style={{ fontSize: 13 }}>{sentence}</div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>
              {grantObject}
            </div>
          </div>
        ) : null}
      </div>
      <DataTable columns={policyColumns} rows={policyRows} rowKey="rowKey" empty="부여된 권한 없음" />
    </div>
  )

  return (
    <Page
      title="유저"
      subtitle="유저와 권한을 관리합니다 — 공개 등록은 없으며 여기서만 생성됩니다."
      actions={
        // 유저 추가는 유저 목록 탭에서만 의미 — 권한 부여 탭에선 숨김(스펙 200 후속: 탭 분리)
        tab === 'users' ? (
          <Button type="primary" onClick={() => setModal(true)}>
            유저 추가
          </Button>
        ) : undefined
      }
    >
      {/* 스펙 200 후속: 유저 목록·권한 부여 탭 분리 — 유저가 늘면 한 화면 세로 나열이 불편(사용자 요청). */}
      <Tabs
        activeKey={tab}
        onChange={(k) => setTab(k as 'users' | 'grants')}
        items={[
          {
            key: 'users',
            label: '유저 목록',
            children: (
              <DataTable columns={columns} rows={users} empty={loading ? '불러오는 중…' : '유저 없음'} />
            ),
          },
          {
            key: 'grants',
            label: '권한 부여',
            children: grantPane,
          },
        ]}
      />

      <CreateUserModal
        open={modal}
        onCancel={() => setModal(false)}
        onCreated={() => {
          setModal(false)
          void load()
        }}
      />
    </Page>
  )
}
