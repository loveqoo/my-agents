/* my-agents admin — 기억 페이지 목록 (스펙 127→128, "일치 검색" 표면).
   엔진(디바운스 서버검색·페이지네이션·total 상시·지속 오류·reqSeq)은 공용 `PagedListShell`(128)로
   추출됐고, 여기는 **메모리 고유**만 남는다: 인라인 편집·삭제(마지막 항목 삭제 시 이전 페이지 보정),
   미구성(enabled=false) 안내, 스코프 라벨. 세션·컬렉션 문서와 같은 셸을 공유(드리프트 0). */
import { useState } from 'react'
import { Alert, Button, Input, Popconfirm, Tooltip } from 'antd'
import { PagedListShell, type ListController } from './PagedListShell'
import { type Column } from '../shared'
import { Icon } from '../icons'
import { type MemoryPageItem, type MemoryPageOut } from '../../api'
import { runWithToast } from '../../hooks'

export function PagedMemoryList({
  scopeKey,
  scopeLabel,
  fetchPage,
  onEdit,
  onDelete,
  refreshKey = 0,
}: {
  scopeKey: string // 스코프(유저/에이전트) 식별자(UUID) — 바뀌면 검색·페이지 초기화. 총계 줄엔 툴팁으로.
  scopeLabel: string // 총계 줄 표기: 사람이 읽는 이름(스펙 220) — "누구의 기억을 보고 있나". UUID는 scopeKey 툴팁.
  fetchPage: (q: string, limit: number, offset: number) => Promise<MemoryPageOut>
  onEdit: (memId: string, text: string) => Promise<void>
  onDelete: (memId: string) => Promise<void>
  refreshKey?: number // 부모가 추가 등으로 재조회를 트리거
}) {
  const [editing, setEditing] = useState<string | null>(null)
  const [editText, setEditText] = useState('')
  const [busy, setBusy] = useState(false)

  const fmtTime = (s: string | null) => (s ? s.slice(0, 19).replace('T', ' ') : '—')

  const saveEdit = async (ctl: ListController, memId: string) => {
    const text = editText.trim()
    if (!text) return
    setBusy(true)
    const ok = await runWithToast(() => onEdit(memId, text), {
      success: '수정됨',
      errorPrefix: '수정 실패',
    })
    setBusy(false)
    if (ok) {
      setEditing(null)
      await ctl.reload()
    }
  }

  const remove = async (ctl: ListController, memId: string) => {
    setBusy(true)
    const ok = await runWithToast(() => onDelete(memId), {
      success: '삭제됨',
      errorPrefix: '삭제 실패',
    })
    setBusy(false)
    if (ok) {
      // 페이지 마지막 항목 삭제로 빈 페이지가 되면 앞 페이지로.
      if (ctl.rowCount === 1 && ctl.page > 1) ctl.setPage(ctl.page - 1)
      else await ctl.reload()
    }
  }

  const columns = (ctl: ListController): Column<MemoryPageItem>[] => [
    {
      key: 'text',
      title: '기억',
      render: (m) =>
        editing === m.id ? (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }} onClick={(e) => e.stopPropagation()}>
            <Input
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              onPressEnter={() => void saveEdit(ctl, m.id)}
              autoFocus
            />
            <Button size="small" type="primary" loading={busy} onClick={() => void saveEdit(ctl, m.id)}>
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
          <Popconfirm title="이 기억을 삭제할까요?" onConfirm={() => void remove(ctl, m.id)} okText="삭제" cancelText="취소">
            <Button size="small" type="text" danger icon={<Icon name="delete" />} />
          </Popconfirm>
        </div>
      ),
    },
  ]

  return (
    <PagedListShell<MemoryPageItem>
      scopeKey={scopeKey}
      fetchPage={fetchPage}
      columns={columns}
      refreshKey={refreshKey}
      searchPlaceholder="기억 본문 부분일치 검색 (전체 대상)"
      countLabel={(total, q) => (
        <>
          {q ? `"${q}" 일치 ` : '전체 '}
          {/* 스펙 220: 이름 위주 표기 + UUID는 진단용 툴팁(호버) — 원본 스코프 식별자는 scopeKey. */}
          {total}건 · 스코프{' '}
          <Tooltip title={`스코프 ID: ${scopeKey}`}>
            <span style={{ cursor: 'help', borderBottom: '1px dotted var(--color-border)' }}>{scopeLabel}</span>
          </Tooltip>
        </>
      )}
      emptyText={(q) => (q ? '일치하는 기억이 없습니다.' : '기억이 없습니다.')}
      disabledAlert={
        <Alert
          type="info"
          showIcon
          title="장기 기억이 비활성/미구성입니다"
          description="임베딩/LLM 모델·에이전트 메모리 설정을 확인하세요."
        />
      }
    />
  )
}
