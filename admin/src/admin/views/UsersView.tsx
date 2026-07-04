/* my-agents admin — Users view (스펙 031): 유저·역할 관리(admin 보호).
   목록 + 활성 토글 + 역할 부여/회수 + 유저 추가 모달. 공개 등록은 없으므로 생성은 여기서만.
   백엔드: GET/POST /admin/users, PATCH active, GET /admin/roles, POST/DELETE roles. */
import { useState, useEffect, useCallback, type ReactNode } from 'react'
import { Tag, Button, Modal, Input, Switch, Select, Form, message, Tooltip, Card, Space } from 'antd'
import { Page, DataTable, StatusPill, type Column } from '../shared'
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
  type AdminUser,
  type RoleInfo,
  type Policy,
} from '../../api'

const ROLE_COLOR: Record<string, string> = { admin: 'volcano', member: 'blue' }

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

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [u, r, p] = await Promise.all([listUsers(), listRoles(), listPolicies()])
      setUsers(u)
      setRoles(r)
      setPolicies(p)
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
    try {
      const updated = await setUserActive(u.id, !u.is_active)
      setUsers((xs) => xs.map((x) => (x.id === u.id ? updated : x)))
    } catch {
      message.error('상태 변경 실패')
    }
  }

  const onGrant = async (u: AdminUser, role: string) => {
    try {
      const updated = await grantRole(u.id, role)
      setUsers((xs) => xs.map((x) => (x.id === u.id ? updated : x)))
    } catch {
      message.error('역할 부여 실패')
    }
  }

  const onRevoke = async (u: AdminUser, role: string) => {
    try {
      const updated = await revokeRole(u.id, role)
      setUsers((xs) => xs.map((x) => (x.id === u.id ? updated : x)))
    } catch {
      message.error('역할 회수 실패')
    }
  }

  /* ---- 능력 부여(정책) — 스펙 177 P3 ---- */
  const subjectLabel = (subject: string): ReactNode => {
    const u = users.find((x) => x.id === subject)
    if (u) return u.email
    const r = roles.find((x) => x.name === subject)
    if (r) return <Tag color={ROLE_COLOR[r.name]}>{r.name}</Tag>
    return subject
  }

  const onRevokePolicy = async (p: Policy) => {
    try {
      await revokePolicy(p.subject, p.object, p.action)
      message.success('능력을 회수했습니다')
      void load()
    } catch {
      message.error('능력 회수 실패')
    }
  }

  const [grantSubject, setGrantSubject] = useState<string | undefined>(undefined)
  const [grantKind, setGrantKind] = useState<string | undefined>(undefined)
  const [grantName, setGrantName] = useState('')
  const [granting, setGranting] = useState(false)

  const grantObject = grantKind
    ? grantName.trim()
      ? `capability:${grantKind}:${grantName.trim()}`
      : `capability:${grantKind}`
    : ''

  const onGrantPolicy = async () => {
    if (!grantSubject || !grantKind) return
    setGranting(true)
    try {
      await grantPolicy({ subject: grantSubject, object: grantObject, action: 'invoke' })
      message.success('능력을 부여했습니다')
      setGrantSubject(undefined)
      setGrantKind(undefined)
      setGrantName('')
      void load()
    } catch {
      message.error('능력 부여 실패')
    } finally {
      setGranting(false)
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
      title: '능력',
      render: (p) => <Tag style={{ fontFamily: 'var(--font-family-code)' }}>{p.object}</Tag>,
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
    {
      key: 'verified',
      title: '상태',
      render: (u) =>
        u.is_active ? (
          <StatusPill color="var(--green-6)" label="활성" />
        ) : (
          <StatusPill color="var(--gray-6)" label="비활성" />
        ),
    },
  ]

  return (
    <Page
      title="유저"
      subtitle="계정과 역할을 관리합니다 — 공개 등록은 없으며 여기서만 생성됩니다."
      actions={
        <Button type="primary" onClick={() => setModal(true)}>
          유저 추가
        </Button>
      }
    >
      <DataTable columns={columns} rows={users} empty={loading ? '불러오는 중…' : '유저 없음'} />

      <Card title="능력 부여 (정책)" style={{ marginTop: 24 }}>
        <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 12 }}>
          능력을 이 역할/유저에 엽니다. member는 부여 전엔 능력을 쓸 수 없습니다(기본 거부).
        </div>
        <Space wrap align="end" style={{ marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 4 }}>대상</div>
            <Select<string>
              style={{ minWidth: 220 }}
              placeholder="대상 선택"
              value={grantSubject}
              onChange={setGrantSubject}
              options={[
                { label: '역할', options: roles.map((r) => ({ value: r.name, label: `역할: ${r.name}` })) },
                { label: '유저', options: users.map((u) => ({ value: u.id, label: `유저: ${u.email}` })) },
              ]}
            />
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 4 }}>능력 종류</div>
            <Select<string>
              style={{ minWidth: 110 }}
              placeholder="종류"
              value={grantKind}
              onChange={setGrantKind}
              options={[
                { value: 'mcp', label: 'mcp' },
                { value: 'rag', label: 'rag' },
                { value: 'agent', label: 'agent' },
              ]}
            />
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 4 }}>이름/서버(선택)</div>
            <Input
              style={{ minWidth: 200 }}
              placeholder="이름/서버(선택, 비우면 전체)"
              value={grantName}
              onChange={(e) => setGrantName(e.target.value)}
            />
          </div>
          <div style={{ color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)', fontSize: 13 }}>
            {grantObject || 'capability:…'}
          </div>
          <Button
            type="primary"
            loading={granting}
            disabled={!grantSubject || !grantKind}
            onClick={() => void onGrantPolicy()}
          >
            부여
          </Button>
        </Space>
        <DataTable columns={policyColumns} rows={policyRows} rowKey="rowKey" empty="부여된 능력 없음" />
      </Card>

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
