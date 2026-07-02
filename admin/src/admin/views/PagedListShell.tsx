/* my-agents admin — 페이지 목록 공용 셸 (스펙 128).
   127 PagedMemoryList의 엔진(디바운스 서버검색·페이지네이션·total 상시·지속 오류·reqSeq stale 가드)을
   추출한 공용 부품 — 메모리·세션·컬렉션 문서가 공유한다(두 벌 엔진=드리프트라 한 곳으로, 126 동형).
   도메인 고유(컬럼·행 액션·필터·미구성 안내)는 props로 주입.

   정직성 계약: 백엔드 실패는 **지속 오류 Alert**(사라지는 토스트 금지 — learning 125 실패≠0건),
   enabled=false(메모리 미구성)는 disabledAlert(0건과 구분), total·검색어를 상시 표기해 0건에도
   1차 진단이 된다.

   재조회 트리거 설계: fetchPage는 **ref로 고정**(소비자가 인라인 클로저·필터 캡처를 넘겨도 identity
   변화로 재조회 루프가 안 생김) — 재조회는 오직 [q, page, scopeKey, refreshKey, pageResetKey]로.
   scopeKey 변경=전체 리셋(검색어 포함), pageResetKey 변경=page만 1로(검색어 보존 — 세션 status 필터
   전환이 검색어를 유지하는 기존 UX). */
import { useState, useEffect, useCallback, useRef, type ReactNode } from 'react'
import { Alert, Input, Pagination } from 'antd'
import { DataTable, type Column } from '../shared'
import { Icon } from '../icons'

/** 페이지 응답 — 도메인 확장(세션 counts 등)은 extra로 통과(셸은 onExtra로 되돌릴 뿐, 렌더는 소비자). */
export interface PagedResult<T, X = unknown> {
  items: T[]
  total: number // q 적용 후 전체 건수
  enabled?: boolean // 기본 true. false=미구성(disabledAlert 표시, 메모리 전용 계약)
  extra?: X
}

/** 셸이 컬럼 함수에 노출하는 제어 핸들 — 인라인 편집/삭제가 재조회·페이지 보정에 쓴다. */
export interface ListController {
  reload: () => Promise<void>
  page: number
  setPage: (p: number) => void
  rowCount: number // 현재 페이지 행 수(마지막 항목 삭제 → 이전 페이지 판단)
}

export function PagedListShell<T, X = unknown>({
  scopeKey,
  fetchPage,
  columns,
  onRowClick,
  rowKey = 'id',
  pageSize = 20,
  refreshKey = 0,
  pageResetKey = 0,
  searchPlaceholder = '검색',
  leftSlot,
  onExtra,
  countLabel,
  emptyText,
  disabledAlert,
  errorTitle = '목록 조회 실패',
}: {
  scopeKey: string // 바뀌면 검색·페이지 전체 리셋
  fetchPage: (q: string, limit: number, offset: number) => Promise<PagedResult<T, X>>
  columns: Column<T>[] | ((ctl: ListController) => Column<T>[]) // 함수형=행 액션이 reload/setPage 접근
  onRowClick?: (row: T) => void
  rowKey?: string
  pageSize?: number
  refreshKey?: number // 부모가 추가/업로드 후 재조회 트리거
  pageResetKey?: string | number // 바뀌면 page=1(검색어 보존 — 필터 전환용)
  searchPlaceholder?: string
  leftSlot?: ReactNode // 검색창 왼쪽 슬롯(Radio/Segmented 필터 — 상태는 소비자 소유)
  onExtra?: (extra: X | undefined) => void // 응답 extra(세션 counts) 소비자로 되돌림
  countLabel?: (total: number, q: string) => ReactNode // 기본 "전체/일치 N건"
  emptyText?: ReactNode | ((q: string) => ReactNode)
  disabledAlert?: ReactNode // enabled=false 시(메모리 미구성). 항상 true인 도메인은 불필요
  errorTitle?: string
}) {
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [rows, setRows] = useState<T[]>([])
  const [total, setTotal] = useState(0)
  const [enabled, setEnabled] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  // 요청 시퀀스 — 페이지/검색/필터 연타로 밀린 늦은 응답이 최신 상태를 덮지 못하게(127 reqSeq).
  const reqSeq = useRef(0)
  // fetchPage/onExtra는 ref로 — 소비자의 인라인 클로저(필터 캡처)가 매 렌더 새 identity여도
  // 재조회 루프가 안 생긴다. 항상 최신 클로저를 읽는다.
  const fetchRef = useRef(fetchPage)
  fetchRef.current = fetchPage
  const extraRef = useRef(onExtra)
  extraRef.current = onExtra

  // 검색어 디바운스(~300ms) — 확정 시 첫 페이지로(SessionsView 확립 패턴).
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
      const data = await fetchRef.current(q, pageSize, (page - 1) * pageSize)
      if (seq !== reqSeq.current) return // 늦은 응답 폐기
      setRows(data.items)
      setTotal(data.total)
      setEnabled(data.enabled !== false)
      extraRef.current?.(data.extra)
    } catch (e) {
      if (seq !== reqSeq.current) return
      const m = e instanceof Error ? e.message : '목록 조회 실패'
      setError(m) // 지속 표시만(0건 위장 금지·사라지는 토스트 중복 금지, 125·codex 128 #2)
      setRows([])
      setTotal(0)
    } finally {
      if (seq === reqSeq.current) setLoading(false)
    }
  }, [q, page, pageSize])

  // 안정 identity reload — 컬럼 함수(ctl)가 잡아도 최신 load를 실행.
  const loadRef = useRef(load)
  loadRef.current = load
  const reload = useCallback(() => loadRef.current(), [])

  // 리셋과 조회를 **한 효과에서 조율**(codex 128 #1) — 리셋이 필요한 렌더에서는 fetch를 건너뛰어
  // 구 페이지/구 검색어로의 과도기 요청 자체를 없앤다(reqSeq는 "다음 요청 시작 후"만 보호하므로
  // 빠른 응답이 잠깐 커밋될 수 있었다). state가 정착하면 q/page(load deps) 변경으로 재실행돼 조회.
  const scopeRef = useRef(scopeKey)
  const resetRef = useRef(pageResetKey)
  useEffect(() => {
    let skip = false
    if (scopeRef.current !== scopeKey) {
      // 스코프 전환 = 전체 리셋(검색어 포함). 이미 깨끗하면 리셋 없이 바로 조회.
      scopeRef.current = scopeKey
      resetRef.current = pageResetKey
      setSearch('')
      if (q !== '') {
        setQ('')
        skip = true
      }
      if (page !== 1) {
        setPage(1)
        skip = true
      }
    } else if (resetRef.current !== pageResetKey) {
      // 필터 전환 = page만 1로(검색어 보존). page가 이미 1이면 바로 새 필터로 조회.
      resetRef.current = pageResetKey
      if (page !== 1) {
        setPage(1)
        skip = true
      }
    }
    if (!skip) void load()
  }, [load, scopeKey, refreshKey, pageResetKey]) // q·page는 load identity에 접힘

  const ctl: ListController = { reload, page, setPage, rowCount: rows.length }
  const cols = typeof columns === 'function' ? columns(ctl) : columns
  const empty =
    typeof emptyText === 'function' ? emptyText(q) : (emptyText ?? (q ? '일치하는 항목이 없습니다.' : '데이터가 없습니다.'))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        {leftSlot}
        <Input
          allowClear
          prefix={<Icon name="search" />}
          placeholder={searchPlaceholder}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 320 }}
        />
        {/* 총계 상시 표기 — 0건이어도 "전체 N건/일치 N건"이 보여 1차 진단(127). */}
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          {loading ? '조회 중…' : (countLabel?.(total, q) ?? `${q ? `"${q}" 일치 ` : '전체 '}${total}건`)}
        </span>
      </div>

      {error ? (
        <Alert type="error" showIcon message={errorTitle} description={error} />
      ) : !enabled ? (
        (disabledAlert ?? null)
      ) : (
        <>
          <DataTable<T> columns={cols} rows={rows} onRowClick={onRowClick} rowKey={rowKey} empty={empty} />
          {total > pageSize ? (
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Pagination
                current={page}
                pageSize={pageSize}
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
