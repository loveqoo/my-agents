/* my-agents admin — Users view (스펙 031): 유저·역할 관리(admin 보호).
   목록 + 활성 토글 + 역할 부여/회수 + 유저 추가 모달. 공개 등록은 없으므로 생성은 여기서만.
   백엔드: GET/POST /admin/users, PATCH active, GET /admin/roles, POST/DELETE roles. */
import { useState, useEffect, useCallback } from 'react'
import { Tag, Button, Modal, Input, Switch, Select, Form, message, Tooltip } from 'antd'
import { Page, DataTable, StatusPill, type Column } from '../shared'
import {
  listUsers,
  createUser,
  setUserActive,
  listRoles,
  grantRole,
  revokeRole,
  type AdminUser,
  type RoleInfo,
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
  const [loading, setLoading] = useState(true)
  const [modal, setModal] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [u, r] = await Promise.all([listUsers(), listRoles()])
      setUsers(u)
      setRoles(r)
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
