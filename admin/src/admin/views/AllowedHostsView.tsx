/* my-agents admin — SSRF 허용 호스트(allowlist) 관리 (스펙 064).
   net_guard.guard_url(스펙 042)은 사설/루프백/메타데이터 대역으로의 outbound를 기본 차단한다.
   여기에 등록한 host는 그 예외로 통과한다 — A2A 클라이언트·Agent Card fetch/probe·MCP 연결 공용.
   추가/삭제는 **무재시작**(최대 ~10초 내 반영). 백엔드: GET/POST/DELETE /admin/allowed-hosts. */
import { useState } from 'react'
import { Button, Input, Popconfirm, Space, Alert, message, Form, Collapse } from 'antd'
import { Page, Panel, DataTable, type Column } from '../shared'
import { fmtDateTime } from '../format'
import { useAsyncData, runWithToast } from '../../hooks'
import {
  listAllowedHosts,
  addAllowedHost,
  deleteAllowedHost,
  type AllowedHost,
} from '../../api'

export default function AllowedHostsView() {
  // 페치+로딩+에러+stale 가드는 공용 훅으로(스펙 182). mutation 후 reload()로 갱신.
  const { data: rows = [], loading, reload } = useAsyncData(listAllowedHosts, [], {
    errorMsg: '허용 호스트 목록을 불러오지 못했습니다',
  })
  const [host, setHost] = useState('')
  const [note, setNote] = useState('')
  const [adding, setAdding] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)

  const add = async () => {
    const h = host.trim()
    if (!h) {
      message.warning('호스트를 입력하세요')
      return
    }
    setAdding(true)
    // 422(정확 host 아님)·409(중복) detail은 runWithToast가 예외 메시지로 그대로 노출.
    const ok = await runWithToast(() => addAllowedHost(h, note.trim() || null), {
      success: `허용 호스트 추가: ${h} (무재시작, 최대 ~10초 내 반영)`,
    })
    setAdding(false)
    if (ok) {
      setHost('')
      setNote('')
      reload()
    }
  }

  const remove = async (r: AllowedHost) => {
    setDeleting(r.id)
    const ok = await runWithToast(() => deleteAllowedHost(r.id), {
      success: `허용 호스트 삭제: ${r.host}`,
      error: '삭제 실패',
    })
    setDeleting(null)
    if (ok) reload()
  }

  const columns: Column<AllowedHost>[] = [
    {
      key: 'host',
      title: '호스트',
      render: (r) => (
        <code style={{ fontFamily: 'var(--font-family-code, monospace)', fontWeight: 500 }}>
          {r.host}
        </code>
      ),
    },
    {
      key: 'note',
      title: '메모',
      render: (r) =>
        r.note ? (
          <span style={{ fontSize: 13 }}>{r.note}</span>
        ) : (
          <span style={{ color: 'var(--color-text-tertiary)' }}>—</span>
        ),
    },
    {
      key: 'created_at',
      title: '추가 시각',
      render: (r) => (
        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>
          {r.created_at ? fmtDateTime(r.created_at) : '—'}
        </span>
      ),
    },
    {
      key: 'actions',
      title: '',
      render: (r) => (
        <Popconfirm
          title="삭제하시겠습니까?"
          description={`'${r.host}'를 allowlist에서 제거하면 그 host로의 사설대역 요청이 다시 차단됩니다.`}
          okText="삭제"
          cancelText="취소"
          okButtonProps={{ danger: true }}
          onConfirm={() => void remove(r)}
        >
          <Button size="small" danger loading={deleting === r.id}>
            삭제
          </Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <Page
      title="허용 호스트"
      subtitle="SSRF 가드가 기본 차단하는 사설/루프백 대역 중, 의도적으로 통과시킬 host의 allowlist입니다(무재시작)."
      actions={
        <Button onClick={reload} loading={loading}>
          새로고침
        </Button>
      }
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 8 }}
        title="보안 주의 — host 추가는 SSRF 예외를 여는 행위입니다"
        description="여기 등록한 host는 사설/루프백/메타데이터 대역이라도 서버의 바깥(outbound) 요청이 통과합니다 — 신뢰하는 대상만 추가하세요."
      />
      {/* 스펙 229·230: 핵심 한 문장만 상시, 자세한 배경·규칙은 접이식(기본 접힘) — 필요할 때만 펼침. */}
      <Collapse
        ghost
        size="small"
        style={{ marginBottom: 16 }}
        items={[
          {
            key: 'ssrf',
            label: 'SSRF가 무엇인가요?',
            children: (
              <p style={{ margin: 0, color: 'var(--color-text-secondary)', fontSize: 13 }}>
                <b>SSRF(Server-Side Request Forgery, 서버 측 요청 위조)</b>는 공격자가 서버를 속여, 원래는
                바깥에서 닿을 수 없는 내부망·클라우드 메타데이터(예: 169.254.169.254)·로컬 서비스로 요청을
                보내게 만드는 공격입니다. 그래서 이 서버는 사설·루프백·메타데이터 대역으로 나가는 요청을{' '}
                <b>기본 차단</b>하고, 이 화면에 추가한 host만 그 차단의 <b>예외</b>가 됩니다 — 통과 경로는
                A2A·MCP·Agent Card이며, 개발용 mock(예: 127.0.0.1)처럼 신뢰하는 대상만, 와일드카드·CIDR·포트·
                스킴 없이 <b>정확 host</b>로만 등록하세요.
              </p>
            ),
          },
        ]}
      />

      <Panel style={{ padding: 20, marginBottom: 20 }}>
        <h4 style={{ margin: '0 0 16px', fontSize: 16 }}>호스트 추가</h4>
        {/* antd Form은 레이아웃 전용(스펙 187 Phase 3) — 입력 상태는 기존 controlled 그대로(name 미지정). */}
        {/* 스펙 228: 짧은 두 필드(호스트·메모)를 나란히 — 세로 여백 압축. */}
        <Form layout="vertical" component="div">
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <Form.Item
              label="호스트"
              extra="정확 host(이름 또는 IP)만 — 와일드카드/CIDR/포트/스킴 불가"
              style={{ marginBottom: 12 }}
            >
              <Input
                value={host}
                onChange={(e) => setHost(e.target.value)}
                onPressEnter={() => void add()}
                placeholder="예: 127.0.0.1 또는 agent.internal"
                style={{ width: 320, fontFamily: 'var(--font-family-code, monospace)' }}
              />
            </Form.Item>
            <Form.Item label="메모(선택)" style={{ marginBottom: 12 }}>
              <Input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                onPressEnter={() => void add()}
                placeholder="왜 열었는지 — 예: dev mock A2A"
                maxLength={200}
                style={{ width: 320 }}
              />
            </Form.Item>
          </div>
          <Space>
            <Button type="primary" onClick={() => void add()} loading={adding} disabled={!host.trim()}>
              추가
            </Button>
          </Space>
        </Form>
      </Panel>

      <h4 style={{ margin: '0 0 12px', fontSize: 16 }}>등록된 허용 호스트</h4>
      <DataTable
        columns={columns}
        rows={rows}
        empty={loading ? '불러오는 중…' : '등록된 허용 호스트 없음 — 공인(global) 대역만 통과합니다.'}
      />
    </Page>
  )
}
