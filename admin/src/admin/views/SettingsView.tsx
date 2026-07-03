/* my-agents admin — 앱 설정 (스펙 153). 소수의 전역 설정을 무재시작 변경.
   키는 백엔드 닫힌 집합과 1:1 — 새 설정은 백엔드 _KEYS에 추가 후 여기에 폼을 붙인다. */
import { useEffect, useState } from 'react'
import { Button, Input, message } from 'antd'
import { Page, Panel } from '../shared'
import { getAppSettings, putAppSetting } from '../../api'

export default function SettingsView() {
  const [orgName, setOrgName] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getAppSettings()
      .then((s) => setOrgName(String(s.a2a_org_name ?? '')))
      .catch((e) => message.error(e instanceof Error ? e.message : '설정을 불러오지 못했습니다'))
      .finally(() => setLoading(false))
  }, [])

  const save = async () => {
    if (!orgName.trim()) {
      message.warning('organization 이름을 입력하세요')
      return
    }
    setSaving(true)
    try {
      const r = await putAppSetting('a2a_org_name', orgName.trim())
      setOrgName(String(r.a2a_org_name))
      message.success('저장했습니다 — A2A 카드에 즉시 반영됩니다(재시작 불요)')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '저장에 실패했습니다')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Page title="설정" subtitle="전역 설정 — 저장 즉시 반영(재시작 불요)">
      <Panel style={{ maxWidth: 640, padding: 20 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--color-text-heading)' }}>A2A organization</div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 2 }}>
              A2A로 공개한 에이전트의 카드(provider.organization)에 표기되는 조직 이름입니다.
            </div>
          </div>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 360 }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>organization 이름</span>
            <Input
              placeholder="예: acme-lab"
              value={orgName}
              disabled={loading}
              maxLength={80}
              onChange={(e) => setOrgName(e.target.value)}
            />
          </label>
          <Button type="primary" loading={saving} disabled={loading} onClick={() => void save()} style={{ alignSelf: 'flex-start' }}>
            저장
          </Button>
        </div>
      </Panel>
    </Page>
  )
}
