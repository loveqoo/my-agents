/* my-agents admin — SSRF 허용 호스트(allowlist) 관리 (스펙 064).
   net_guard.guard_url(스펙 042)은 사설/루프백/메타데이터 대역으로의 outbound를 기본 차단한다.
   여기에 등록한 host는 그 예외로 통과한다 — A2A 클라이언트·Agent Card fetch/probe·MCP 연결 공용.
   추가/삭제는 **무재시작**(최대 ~10초 내 반영). 백엔드: GET/POST/DELETE /admin/allowed-hosts. */
import { useState, useEffect, useCallback } from 'react'
import { Button, Input, Popconfirm, Space, Alert, message } from 'antd'
import { Page, Panel, DataTable, Desc, type Column } from '../shared'
import {
  listAllowedHosts,
  addAllowedHost,
  deleteAllowedHost,
  type AllowedHost,
} from '../../api'

export default function AllowedHostsView() {
  const [rows, setRows] = useState<AllowedHost[]>([])
  const [loading, setLoading] = useState(true)
  const [host, setHost] = useState('')
  const [note, setNote] = useState('')
  const [adding, setAdding] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await listAllowedHosts())
    } catch {
      message.error('허용 호스트 목록을 불러오지 못했습니다')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const add = async () => {
    const h = host.trim()
    if (!h) {
      message.warning('호스트를 입력하세요')
      return
    }
    setAdding(true)
    try {
      await addAllowedHost(h, note.trim() || null)
      message.success(`허용 호스트 추가: ${h} (무재시작, 최대 ~10초 내 반영)`)
      setHost('')
      setNote('')
      await load()
    } catch (e) {
      // 백엔드 422(정확 host 아님: 와일드카드/CIDR/포트/스킴 등)·409(중복)의 detail을 그대로 노출.
      message.error(e instanceof Error ? e.message : '추가 실패')
    } finally {
      setAdding(false)
    }
  }

  const remove = async (r: AllowedHost) => {
    setDeleting(r.id)
    try {
      await deleteAllowedHost(r.id)
      message.success(`허용 호스트 삭제: ${r.host}`)
      await load()
    } catch {
      message.error('삭제 실패')
    } finally {
      setDeleting(null)
    }
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
          {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
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
        <Button onClick={() => void load()} loading={loading}>
          새로고침
        </Button>
      }
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message="보안 주의 — host 추가는 SSRF 예외를 여는 행위입니다"
        description="여기 등록한 host는 사설/루프백/메타데이터 대역이라도 서버의 outbound 요청(A2A·MCP·Agent Card)이 통과합니다. 개발용 mock(예: 127.0.0.1) 등 의도된 대상만 추가하세요. 와일드카드·CIDR·포트·스킴은 허용되지 않습니다(정확 host만)."
      />

      <Panel style={{ padding: 20, marginBottom: 20 }}>
        <h4 style={{ margin: '0 0 16px', fontSize: 16 }}>호스트 추가</h4>
        <Desc label="호스트">
          <Input
            value={host}
            onChange={(e) => setHost(e.target.value)}
            onPressEnter={() => void add()}
            placeholder="예: 127.0.0.1 또는 agent.internal"
            style={{ maxWidth: 320, fontFamily: 'var(--font-family-code, monospace)' }}
          />
          <span style={{ marginInlineStart: 12, color: 'var(--color-text-tertiary)', fontSize: 13 }}>
            정확 host(이름 또는 IP)만 — 와일드카드/CIDR/포트/스킴 불가
          </span>
        </Desc>
        <Desc label="메모(선택)">
          <Input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onPressEnter={() => void add()}
            placeholder="왜 열었는지 — 예: dev mock A2A"
            maxLength={200}
            style={{ maxWidth: 320 }}
          />
        </Desc>
        <div style={{ marginTop: 16 }}>
          <Space>
            <Button type="primary" onClick={() => void add()} loading={adding} disabled={!host.trim()}>
              추가
            </Button>
          </Space>
        </div>
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
