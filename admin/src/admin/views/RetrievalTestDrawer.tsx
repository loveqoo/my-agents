/* my-agents admin — 검색시험 드로어 공유 셸 (스펙 097).
   컬렉션 "검색 시험"(072)과 메모리 "조회 시험"(084)이 같은 "검색 코어 시험" UI를 각각 구현해
   드리프트가 났던 걸 한 컴포넌트로 통합. 도메인 차이(라벨·결과메타·비활성 안내·enabled 계약)는
   props로 주입 → 어댑터는 얇게, 이후 한 곳 수정이 양쪽 반영(covering-guard의 UI판).

   정직성 계약(084): onSearch가 돌려주는 `enabled`가 false면 결과 대신 `disabledAlert`를 보인다 —
   "미구성(enabled=false)"과 "0건 회상(enabled=true & 빈 results)"을 구분한다(None≠[]). */
import { useState, useEffect, useRef, type ReactNode } from 'react'
import { Drawer, Input, InputNumber, Button, Tag, Alert, message } from 'antd'
import { Icon } from '../icons'

const { TextArea } = Input

/** 두 도메인 결과의 공통 필드. 도메인별 나머지 필드는 renderMeta가 흡수. */
export interface RetrievalHit {
  score: number // 내림차순(1.0=가장 관련/동일)
  text: string
}

/** onSearch 정규화 반환 — enabled는 "백엔드 가용성"(메모리는 실제 값, 컬렉션은 항상 true). */
export interface RetrievalOut<H extends RetrievalHit> {
  results: H[]
  enabled: boolean
}

export function RetrievalTestDrawer<H extends RetrievalHit>({
  open,
  title,
  scopeKey,
  hint,
  preAlert,
  disabledAlert,
  queryPlaceholder,
  limitLabel,
  runLabel,
  scoreLabel,
  countLabel,
  emptyMessage,
  emptyQueryWarn,
  noResultInfo,
  errorFallback,
  renderMeta,
  onClose,
  onSearch,
  defaultLimit = 4,
}: {
  open: boolean
  title: string
  scopeKey: string // 스코프(컬렉션/에이전트/유저) 식별자 — 바뀌면 질의·결과 초기화
  hint: ReactNode // 상단 설명
  preAlert?: ReactNode // 질의 전에도 항상 보이는 안내(컬렉션 !ready). 없으면 미표시
  disabledAlert?: ReactNode // enabled=false일 때 결과 대신 표시(메모리 미구성). enabled 항상 true면 불필요
  queryPlaceholder: string
  limitLabel: string // 'top_k (1–10)' / 'limit (1–10)'
  runLabel: string // '검색' / '조회'
  scoreLabel: string // '유사도' / '관련도'
  countLabel: (n: number) => string // (n) => '결과 N건' / '회상 N건'
  emptyMessage: string // 인라인: 결과 0건 텍스트
  emptyQueryWarn: string // 빈 질의 warning
  noResultInfo: string // 0건일 때 message.info
  errorFallback: string // 예외 시 fallback 메시지
  renderMeta: (hit: H) => ReactNode // 결과 카드 메타(컬렉션 filename / 메모리 scope·type)
  onClose: () => void
  onSearch: (query: string, limit: number) => Promise<RetrievalOut<H>>
  defaultLimit?: number
}) {
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(defaultLimit)
  const [out, setOut] = useState<RetrievalOut<H> | null>(null)
  const [searching, setSearching] = useState(false)
  // 요청 시퀀스 — 스코프 전환·후속 질의로 밀린 늦은 응답이 다른 스코프 결과를 덮어쓰지 못하게 한다
  // (원본 072/084 두 드로어에 잠재하던 stale-async 스코프 유출; 통합 셸에서 한 번에 봉합).
  const reqSeq = useRef(0)

  // 스코프 전환 시 이전 질의/결과 초기화 + 진행 중 요청 무효화(072/084 패턴).
  useEffect(() => {
    reqSeq.current++
    setQuery('')
    setOut(null)
    setSearching(false)
  }, [scopeKey])

  const run = async () => {
    if (!query.trim()) {
      message.warning(emptyQueryWarn)
      return
    }
    const seq = ++reqSeq.current
    setSearching(true)
    try {
      const res = await onSearch(query.trim(), limit)
      if (seq !== reqSeq.current) return // 스코프 전환/후속 요청에 밀림 — 늦은 결과 폐기
      setOut(res)
      if (res.enabled && !res.results.length) message.info(noResultInfo)
    } catch (e) {
      if (seq !== reqSeq.current) return
      // 4xx(입력·권한)·5xx(임베딩/검색 실패) — 서버 메시지를 그대로 노출.
      message.error(e instanceof Error ? e.message : errorFallback)
    } finally {
      if (seq === reqSeq.current) setSearching(false)
    }
  }

  return (
    <Drawer open={open} width={640} title={title} onClose={onClose} destroyOnHidden>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{hint}</span>
        {preAlert ?? null}
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
          <TextArea
            rows={2}
            placeholder={queryPlaceholder}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onPressEnter={(e) => {
              e.preventDefault()
              void run()
            }}
            style={{ flex: 1 }}
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: 120 }}>
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{limitLabel}</span>
            <InputNumber min={1} max={10} style={{ width: '100%' }} value={limit} onChange={(v) => setLimit(v ?? defaultLimit)} />
            <Button type="primary" icon={<Icon name="search" />} loading={searching} onClick={() => void run()}>
              {runLabel}
            </Button>
          </div>
        </div>

        {out !== null ? (
          !out.enabled ? (
            disabledAlert ?? null
          ) : out.results.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-heading)' }}>{countLabel(out.results.length)}</div>
              {out.results.map((h, i) => (
                <div
                  key={i}
                  style={{
                    padding: 12,
                    border: '1px solid var(--color-border-secondary)',
                    borderRadius: 'var(--radius-lg)',
                    background: 'var(--gray-2)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                  }}
                >
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <Tag color="blue">#{i + 1}</Tag>
                    <Tag color={h.score >= 0.5 ? 'green' : 'default'}>
                      {scoreLabel} {h.score.toFixed(3)}
                    </Tag>
                    {renderMeta(h)}
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', whiteSpace: 'pre-wrap' }}>{h.text}</div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>{emptyMessage}</div>
          )
        ) : null}
      </div>
    </Drawer>
  )
}
