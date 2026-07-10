import { useState, useEffect } from 'react'
import { Button, Input, Modal } from 'antd'
import { Icon } from '../../icons'
import { Field } from './primitives'

/* ---- 원격 에이전트 연결 — URL 하나로 백엔드가 A2A 카드 fetch·검증·provenance 자동분류(스펙 057) ----
   등록 진입점 단일화. 프론트는 매니페스트를 날조하지 않는다 — URL·토큰만 받아 백엔드(`POST /agents/connect`)에
   위임하면, 카드의 my-agents 확장 유무로 source가 정해진다(있으면 우리가 배포한 SDK=code, 없으면 제3자=external). */
export function ConnectAgentModal({
  open,
  onCancel,
  onConnect,
}: {
  open: boolean
  onCancel: () => void
  onConnect: (data: { url: string; token: string }) => Promise<void>
}) {
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (open) {
      setUrl('')
      setToken('')
      setSubmitting(false)
    }
  }, [open])

  const canSubmit = /^https?:\/\/.+/.test(url.trim()) && !submitting
  const submit = async () => {
    setSubmitting(true)
    try {
      await onConnect({ url: url.trim(), token: token.trim() })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open={open}
      width={560}
      title="원격 에이전트 연결"
      onCancel={onCancel}
      footer={
        <>
          <Button onClick={onCancel}>취소</Button>
          <Button type="primary" icon={<Icon name="check" />} loading={submitting} disabled={!canSubmit} onClick={submit}>
            연결
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Field label="에이전트 URL">
          <Input
            prefix={<Icon name="global" />}
            placeholder="https://agents.acme.example/translate"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onPressEnter={() => canSubmit && submit()}
          />
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 6, display: 'block' }}>
            서버가 A2A 카드를 가져와 검증하고 내부 (Code)/외부를 자동 분류합니다. 베이스 URL이면{' '}
            <code>/.well-known/agent-card.json</code>을 탐색합니다.
          </span>
        </Field>
        <Field label="액세스 토큰 (선택)">
          <Input
            type="password"
            prefix={<Icon name="key" />}
            placeholder="Bearer 인증이 필요할 때만 입력"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </Field>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          로컬/사설 주소(127.0.0.1 등)는 서버 환경변수 <code>A2A_ALLOWED_HOSTS</code>에 추가하고 API를
          재기동하면 연결됩니다.
        </span>
      </div>
    </Modal>
  )
}
