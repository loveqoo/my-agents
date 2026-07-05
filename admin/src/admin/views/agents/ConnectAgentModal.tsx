import { useState, useEffect } from 'react'
import { Button, Input, Modal, Alert } from 'antd'
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
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 0 }}
          message="A2A 에이전트의 URL 하나만 입력하세요. 서버가 카드를 가져와(well-known 관례 포함) 검증하고, 우리가 배포한 SDK 에이전트인지(코드) 제3자인지(외부) 자동으로 판별합니다."
        />
        <Field label="에이전트 URL">
          <Input
            prefix={<Icon name="global" />}
            placeholder="https://agents.acme.example/translate  (또는 /.well-known/agent-card.json)"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onPressEnter={() => canSubmit && submit()}
          />
        </Field>
        <Field label="액세스 토큰 (선택)">
          <Input
            type="password"
            prefix={<Icon name="key" />}
            placeholder="호출 시 Bearer 인증이 필요하면 입력 (없으면 비워두세요)"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </Field>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          URL은 카드 문서 또는 서비스 베이스를 가리킬 수 있습니다. 베이스면 서버가 `/.well-known/agent-card.json`을 탐색합니다.
        </span>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          로컬/사설 endpoint(127.0.0.1 · 10.x · 192.168.x · ::1)는 SSRF 보호로 기본 차단됩니다 — 서버 환경변수{' '}
          <code>A2A_ALLOWED_HOSTS</code>에 해당 호스트를 추가(쉼표구분)하고 API를 재기동해야 호출됩니다. 내 로컬 에이전트를
          A2A로 노출해 테스트할 때 필요합니다(예: <code>A2A_ALLOWED_HOSTS=127.0.0.1</code>).
        </span>
      </div>
    </Modal>
  )
}
