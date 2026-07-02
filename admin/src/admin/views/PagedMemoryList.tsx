/* my-agents admin — 기억 페이지 목록 (스펙 127, "일치 검색" 표면).
   메모리는 계속 증가하므로 전량 렌더 대신 **서버 페이지네이션**(SessionsView 확립 패턴 이식):
   디바운스 검색 → 서버 부분일치(전체 스코프 대상) → DataTable + Pagination. 행에서 바로 수정·삭제.

   정직성: enabled=false(미구성)는 안내 Alert(0건과 구분, 084 계약), 백엔드 실패(502)는 **지속 오류**
   (사라지는 토스트 금지 — learning 125 실패≠0건). 총 건수·스코프를 상시 표기해 0건에도 1차 진단이 된다. */
import { useState, useEffect, useCallback, useRef } from 'react'
import { Alert, Button, Input, Pagination, Popconfirm, message } from 'antd'
import { DataTable, type Column } from '../shared'
import { Icon } from '../icons'
import { type MemoryPageItem, type MemoryPageOut } from '../../api'

const PAGE_SIZE = 20

export function PagedMemoryList({
  scopeKey,
  scopeLabel,
  fetchPage,
  onEdit,
  onDelete,
  refreshKey = 0,
}: {
  scopeKey: string // 스코프(유저/에이전트) 식별자 — 바뀌면 검색·페이지 초기화
  scopeLabel: string // 총계 줄에 표기(진단 겸용: "누구의 기억을 보고 있나")
  fetchPage: (q: string, limit: number, offset: number) => Promise<MemoryPageOut>
  onEdit: (memId: string, text: string) => Promise<void>
  onDelete: (memId: string) => Promise<void>
  refreshKey?: number // 부모가 추가 등으로 재조회를 트리거
}) {
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [rows, setRows] = useState<MemoryPageItem[]>([])
  const [total, setTotal] = useState(0)
  const [enabled, setEnabled] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [busy, setBusy] = useState(false)
  // 요청 시퀀스 — 페이지/검색 연타로 밀린 늦은 응답이 최신 상태를 덮지 못하게(RetrievalTestPanel reqSeq 동형).
  const reqSeq = useRef(0)

  // 스코프 전환 → 검색·페이지 초기화(다른 스코프 결과 잔존 방지).
  useEffect(() => {
    setSearch('')
    setQ('')
    setPage(1)
  }, [scopeKey])

  // 검색어 디바운스(~300ms) — 확정 시 첫 페이지로(SessionsView 패턴).
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(search.trim())
      setPage(1)
    }, 300)
    return () => clearTimeout(t)
  }, [search])

  const load = useCallback(async () => {
    const seq = ++reqSeq.current
    setLoading(true)
    setError(null)
    try {
      const data = await fetchPage(q, PAGE_SIZE, (page - 1) * PAGE_SIZE)
      if (seq !== reqSeq.current) return // 페이지/검색 연타에 밀린 늦은 응답 폐기
      setRows(data.items)
      setTotal(data.total)
      setEnabled(data.enabled)
    } catch (e) {
      if (seq !== reqSeq.current) return
      // 502(백엔드 실패) 등 — 지속 표시(0건으로 위장 금지, 125).
      setError(e instanceof Error ? e.message : '목록 조회 실패')
      setRows([])
      setTotal(0)
    } finally {
      if (seq === reqSeq.current) setLoading(false)
    }
  }, [fetchPage, q, page])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  const saveEdit = async (memId: string) => {
    const text = editText.trim()
    if (!text) return
    setBusy(true)
    try {
      await onEdit(memId, text)
      setEditing(null)
      await load()
      message.success('수정됨')
    } catch (e) {
      message.error('수정 실패: ' + (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (memId: string) => {
    setBusy(true)
    try {
      await onDelete(memId)
      // 페이지 마지막 항목 삭제로 빈 페이지가 되면 앞 페이지로.
      if (rows.length === 1 && page > 1) setPage(page - 1)
      else await load()
      message.success('삭제됨')
    } catch (e) {
      message.error('삭제 실패: ' + (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const fmtTime = (s: string | null) => (s ? s.slice(0, 19).replace('T', ' ') : '—')

  const columns: Column<MemoryPageItem>[] = [
    {
      key: 'text',
      title: '기억',
      render: (m) =>
        editing === m.id ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }} onClick={(e) => e.stopPropagation()}>
            <Input
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              onPressEnter={() => void saveEdit(m.id)}
              autoFocus
            />
            <Button size="small" type="primary" loading={busy} onClick={() => void saveEdit(m.id)}>
              저장
            </Button>
            <Button size="small" onClick={() => setEditing(null)}>
              취소
            </Button>
          </div>
        ) : (
          <span style={{ fontSize: 13, whiteSpace: 'pre-wrap' }}>{m.text}</span>
        ),
    },
    {
      key: 'created',
      title: '생성',
      width: 150,
      hideBelow: 'lg',
      render: (m) => (
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-family-code)' }}>
          {fmtTime(m.created_at)}
        </span>
      ),
    },
    {
      key: 'actions',
      title: '',
      width: 84,
      render: (m) => (
        <div style={{ display: 'flex', gap: 2 }} onClick={(e) => e.stopPropagation()}>
          <Button
            size="small"
            type="text"
            icon={<Icon name="edit" />}
            onClick={() => {
              setEditing(m.id)
              setEditText(m.text)
            }}
          />
          <Popconfirm title="이 기억을 삭제할까요?" onConfirm={() => void remove(m.id)} okText="삭제" cancelText="취소">
            <Button size="small" type="text" danger icon={<Icon name="delete" />} />
          </Popconfirm>
        </div>
      ),
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <Input
          allowClear
          prefix={<Icon name="search" />}
          placeholder="기억 본문 부분일치 검색 (전체 대상)"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 320 }}
        />
        {/* 총계·스코프 상시 표기 — 0건이어도 "전체 N건 중 0건·어느 스코프"가 보여 1차 진단(127). */}
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          {loading ? '조회 중…' : `${q ? `"${q}" 일치 ` : '전체 '}${total}건`} · 스코프{' '}
          <span style={{ fontFamily: 'var(--font-family-code)' }}>{scopeLabel}</span>
        </span>
      </div>

      {error ? (
        <Alert type="error" showIcon message="목록 조회 실패" description={error} />
      ) : !enabled ? (
        <Alert
          type="info"
          showIcon
          message="장기 기억이 비활성/미구성입니다"
          description="임베딩/LLM 모델·에이전트 메모리 설정을 확인하세요."
        />
      ) : (
        <>
          <DataTable<MemoryPageItem>
            columns={columns}
            rows={rows}
            empty={q ? '일치하는 기억이 없습니다.' : '기억이 없습니다.'}
          />
          {total > PAGE_SIZE ? (
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Pagination
                current={page}
                pageSize={PAGE_SIZE}
                total={total}
                showSizeChanger={false}
                onChange={setPage}
                showTotal={(t) => `총 ${t}건`}
              />
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}
