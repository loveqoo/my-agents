/* 로그인 화면 (스펙 031) — 이메일/비밀번호 → 세션 쿠키.
   미인증(getMe=null)일 때 AuthGate가 이 화면을 띄운다. 성공 시 onSuccess로 me를 다시 조회. */
import { useState } from 'react'
import { Card, Form, Input, Button, Typography, theme } from 'antd'
import { RobotOutlined, LockOutlined, MailOutlined } from '@ant-design/icons'
import { login } from '../api'

// dev 편의: 로컬 개발(import.meta.env.DEV)에서만 시드 admin 계정으로 폼을 미리 채운다 — 매번 비번
// 외우는 마찰 제거. 프로덕션 빌드에선 import.meta.env.DEV=false라 이 분기가 통째로 트리셰이킹돼
// 빈 폼이 나가고 비번 리터럴도 번들에 안 실린다. 값은 .env의 ADMIN_EMAIL/ADMIN_PASSWORD 시드와 일치하며,
// admin/.env의 VITE_DEV_LOGIN_EMAIL/VITE_DEV_LOGIN_PASSWORD로 오버라이드할 수 있다(시드를 바꿨을 때).
const DEV_INITIAL = import.meta.env.DEV
  ? {
      email: import.meta.env.VITE_DEV_LOGIN_EMAIL ?? 'admin@example.com',
      password: import.meta.env.VITE_DEV_LOGIN_PASSWORD ?? 'adminpass123',
    }
  : undefined

export default function LoginScreen({ onSuccess }: { onSuccess: () => void }) {
  const { token } = theme.useToken()
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const onFinish = async (v: { email: string; password: string }) => {
    setLoading(true)
    setErr(null)
    try {
      await login(v.email.trim(), v.password)
      onSuccess()
    } catch (e) {
      setErr(e instanceof Error ? e.message : '로그인 실패')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--color-bg-layout, #f5f5f5)',
      }}
    >
      <Card style={{ width: 380, maxWidth: '90vw' }} styles={{ body: { padding: 32 } }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <span
            style={{
              width: 44,
              height: 44,
              borderRadius: 10,
              background: token.colorPrimary,
              color: '#fff',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <RobotOutlined style={{ fontSize: 24 }} />
          </span>
          <Typography.Title level={4} style={{ margin: '12px 0 0' }}>
            my-agents 로그인
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            관리자에게 발급받은 계정으로 로그인하세요
          </Typography.Text>
        </div>
        <Form
          layout="vertical"
          onFinish={onFinish}
          requiredMark={false}
          disabled={loading}
          initialValues={DEV_INITIAL}
        >
          <Form.Item
            name="email"
            label="이메일"
            rules={[{ required: true, type: 'email', message: '이메일을 입력하세요' }]}
          >
            <Input prefix={<MailOutlined />} placeholder="you@example.com" autoComplete="username" size="large" />
          </Form.Item>
          <Form.Item
            name="password"
            label="비밀번호"
            rules={[{ required: true, message: '비밀번호를 입력하세요' }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="비밀번호"
              autoComplete="current-password"
              size="large"
            />
          </Form.Item>
          {err && (
            <Typography.Text type="danger" style={{ display: 'block', marginBottom: 12, fontSize: 13 }}>
              {err}
            </Typography.Text>
          )}
          <Button type="primary" htmlType="submit" block size="large" loading={loading}>
            로그인
          </Button>
        </Form>
      </Card>
    </div>
  )
}
