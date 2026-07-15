/* my-agents admin — 앱 설정 (스펙 153). 소수의 전역 설정을 무재시작 변경.
   키는 백엔드 닫힌 집합과 1:1 — 새 설정은 백엔드 _KEYS에 추가 후 여기에 폼을 붙인다. */
import { useEffect, useState } from 'react'
import { Button, Input, InputNumber, message } from 'antd'
import { Page, Panel } from '../shared'
import { getAppSettings, putAppSetting } from '../../api'
import { runWithToast } from '../../hooks'

export default function SettingsView() {
  const [orgName, setOrgName] = useState('')
  const [gateRuns, setGateRuns] = useState<number>(0)
  const [gateScore, setGateScore] = useState<number>(0) // 0~100(%) 표시 — 저장은 0~1
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [savingGate, setSavingGate] = useState(false)

  useEffect(() => {
    getAppSettings()
      .then((s) => {
        setOrgName(String(s.a2a_org_name ?? ''))
        setGateRuns(Number(s.eval_gate_min_runs ?? 0))
        setGateScore(Math.round(Number(s.eval_gate_min_score ?? 0) * 100))
      })
      .catch((e) => message.error(e instanceof Error ? e.message : '설정을 불러오지 못했습니다'))
      .finally(() => setLoading(false))
  }, [])

  const save = async () => {
    if (!orgName.trim()) {
      message.warning('organization 이름을 입력하세요')
      return
    }
    setSaving(true)
    await runWithToast(
      async () => {
        const r = await putAppSetting('a2a_org_name', orgName.trim())
        setOrgName(String(r.a2a_org_name))
      },
      { success: '저장했습니다 — A2A 카드에 즉시 반영됩니다(재시작 불요)' },
    )
    setSaving(false)
  }

  const saveGate = async () => {
    setSavingGate(true)
    await runWithToast(
      async () => {
        await putAppSetting('eval_gate_min_runs', gateRuns)
        const r = await putAppSetting('eval_gate_min_score', gateScore / 100)
        setGateScore(Math.round(Number(r.eval_gate_min_score ?? 0) * 100))
      },
      {
        success:
          gateRuns === 0 && gateScore === 0
            ? '저장했습니다 — 게이트가 꺼져 모든 버전을 오픈할 수 있습니다'
            : `저장했습니다 — 성공 평가 ${gateRuns}회 이상·평균 ${gateScore}% 이상이면 오픈됩니다`,
      },
    )
    setSavingGate(false)
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
            {/* 입력 라벨 제거(스펙 250 #8) — 단일 필드라 카드 제목("A2A organization")+설명이 라벨 역할. */}
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
      <Panel style={{ maxWidth: 640, padding: 20, marginTop: 16 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--color-text-heading)' }}>평가 게이트</div>
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 2 }}>
              새 버전은 이 기준을 넘는 평가 실적이 있어야 오픈(배포)됩니다 — 성공 평가 회수와 평균 점수 기준.
              둘 다 0이면 게이트가 꺼집니다. 롤백(이미 오픈됐던 버전 재오픈)은 항상 가능합니다.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 500 }}>최소 성공 평가 회수</span>
              <InputNumber min={0} step={1} value={gateRuns} disabled={loading} onChange={(v) => setGateRuns(Number(v ?? 0))} style={{ width: 160 }} />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 500 }}>최소 평균 점수 (%)</span>
              <InputNumber min={0} max={100} step={5} value={gateScore} disabled={loading} onChange={(v) => setGateScore(Number(v ?? 0))} style={{ width: 160 }} />
            </label>
          </div>
          <Button type="primary" loading={savingGate} disabled={loading} onClick={() => void saveGate()} style={{ alignSelf: 'flex-start' }}>
            저장
          </Button>
        </div>
      </Panel>
    </Page>
  )
}
