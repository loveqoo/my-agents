/* my-agents admin — 검색시험 공용 알맹이 (스펙 097·125·126).
   컬렉션 "검색 시험"(072)과 메모리 "조회 시험"(084)이 공유하는 "검색 코어 시험" 본문을 Drawer에서
   분리(126) — 이제 (a) 컬렉션은 `RetrievalTestDrawer`가 이 패널을 Drawer로 감싸 쓰고, (b) 메모리는
   상세 페이지에서 이 패널을 **인라인 전체 폭**으로 쓴다(넓은 영역 활용). 도메인 차이(라벨·결과메타·
   비활성 안내·enabled 계약)는 props 주입 → 어댑터는 얇게, 한 곳 수정이 세 소비처 반영.

   정직성 계약(084): onSearch가 돌려주는 `enabled`가 false면 결과 대신 `disabledAlert`(메모리 미구성).
   진단(125): diag가 있으면 "왜 0건/실패인지"를 지속 표시. 실패≠0건(diag.error면 빈메시지 억제). */
import { useState, useEffect, useRef, type ReactNode } from 'react'
import { Input, InputNumber, Button, Tag, Alert, Collapse, message } from 'antd'
import { Icon } from '../icons'

const { TextArea } = Input

/** 두 도메인 결과의 공통 필드. 도메인별 나머지 필드는 renderMeta가 흡수. */
export interface RetrievalHit {
  score: number // 내림차순(1.0=가장 관련/동일)
  text: string
  meta?: Record<string, unknown> | null // 엔티티 metadata(스펙 149) — 있으면 카드 하단에 표시
}

/** 검색 진단(스펙 125) — "왜 0건/실패인지". 메모리 경로만 채운다(컬렉션은 undefined). */
export interface SearchDiag {
  configured: boolean
  backendReady: boolean
  embedderModel: string | null
  llmModel: string | null
  error: string | null
  scope: string
  count: number
  stored?: number | null // 스코프 저장 건수(스펙 158, 메모리 전용) — 저장>0인데 회상 0이면 유사도/임베더 문제
}

/** onSearch 정규화 반환 — enabled는 "백엔드 가용성"(메모리는 실제 값, 컬렉션은 항상 true). */
export interface RetrievalOut<H extends RetrievalHit> {
  results: H[]
  enabled: boolean
  diag?: SearchDiag | null // 진단(스펙 125) — 선택
}

/* 지속 진단 패널(스펙 125) — "왜 0건/실패인지". 오류 있으면 기본 펼침. 메모리 경로만 diag를 준다. */
function DiagPanel({ diag }: { diag: SearchDiag }) {
  const status = !diag.configured
    ? { color: 'red', text: '임베딩 미설정' }
    : !diag.backendReady
      ? { color: 'red', text: '백엔드 초기화 실패' }
      : diag.error
        ? { color: 'orange', text: '검색 오류' }
        : { color: 'green', text: '정상' }
  const row = (k: string, v: string, mono = false) => (
    <div style={{ display: 'flex', gap: 8 }}>
      <span style={{ width: 96, color: 'var(--color-text-tertiary)', flex: 'none' }}>{k}</span>
      <span style={{ fontFamily: mono ? 'var(--font-family-code)' : undefined, wordBreak: 'break-all' }}>{v}</span>
    </div>
  )
  return (
    <Collapse
      size="small"
      defaultActiveKey={diag.error ? ['diag'] : []}
      items={[
        {
          key: 'diag',
          label: (
            <span>
              진단 <Tag color={status.color}>{status.text}</Tag>
            </span>
          ),
          children: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12 }}>
              {diag.error ? (
                <Alert
                  type={diag.configured && diag.backendReady ? 'warning' : 'error'}
                  showIcon
                  title={diag.error}
                  style={{ marginBottom: 4 }}
                />
              ) : null}
              {row('임베딩 모델', diag.embedderModel ?? '(미설정)')}
              {row('LLM 모델', diag.llmModel ?? '(미설정)')}
              {row('스코프', diag.scope, true)}
              {/* 저장 건수(스펙 158) — 저장>0인데 회상 0이면 유사도/임베더 문제 신호(진단 error도 함께). */}
              {diag.stored != null ? row('저장 건수', String(diag.stored)) : null}
              {row('회상 건수', String(diag.count))}
              {row('백엔드', diag.configured ? (diag.backendReady ? '준비됨' : '초기화 실패') : '미구성')}
            </div>
          ),
        },
      ]}
    />
  )
}

export interface RetrievalTestPanelProps<H extends RetrievalHit> {
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
  onSearch: (query: string, limit: number) => Promise<RetrievalOut<H>>
  defaultLimit?: number
}

export function RetrievalTestPanel<H extends RetrievalHit>({
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
  onSearch,
  defaultLimit = 4,
}: RetrievalTestPanelProps<H>) {
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(defaultLimit)
  const [out, setOut] = useState<RetrievalOut<H> | null>(null)
  const [errMsg, setErrMsg] = useState<string | null>(null) // 지속 오류(스펙 125) — 사라지는 토스트 대신
  const [searching, setSearching] = useState(false)
  // 요청 시퀀스 — 스코프 전환·후속 질의로 밀린 늦은 응답이 다른 스코프 결과를 덮어쓰지 못하게 한다
  // (원본 072/084 두 드로어에 잠재하던 stale-async 스코프 유출; 통합 셸에서 한 번에 봉합).
  const reqSeq = useRef(0)

  // 스코프 전환 시 이전 질의/결과 초기화 + 진행 중 요청 무효화(072/084 패턴).
  useEffect(() => {
    reqSeq.current++
    setQuery('')
    setOut(null)
    setErrMsg(null)
    setSearching(false)
  }, [scopeKey])

  const run = async () => {
    if (!query.trim()) {
      message.warning(emptyQueryWarn)
      return
    }
    const seq = ++reqSeq.current
    setSearching(true)
    setErrMsg(null)
    try {
      const res = await onSearch(query.trim(), limit)
      if (seq !== reqSeq.current) return // 스코프 전환/후속 요청에 밀림 — 늦은 결과 폐기
      setOut(res)
      // diag.error가 있으면 "0건"이 아니라 *실패*다 — "회상 없음" 토스트를 억제(codex 125 M2).
      if (res.enabled && !res.results.length && !res.diag?.error) message.info(noResultInfo)
    } catch (e) {
      if (seq !== reqSeq.current) return
      // 4xx(입력·권한)·5xx·네트워크 — 서버 메시지를 그대로. 토스트는 사라지므로 **지속 오류**로도 남긴다
      // (스펙 125: 다른 디바이스서 검색 실패가 깜빡 후 빈 화면이 되던 걸 방지).
      const m = e instanceof Error ? e.message : errorFallback
      setErrMsg(m)
      setOut(null)
      message.error(m)
    } finally {
      if (seq === reqSeq.current) setSearching(false)
    }
  }

  return (
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
                {h.meta && Object.keys(h.meta).length > 0 ? (
                  // 엔티티 metadata(스펙 149) — 유사도 검색 결과로 원본 행(각 테이블 id)을 특정하는 축
                  <code
                    style={{
                      fontSize: 12,
                      fontFamily: 'var(--font-family-code)',
                      color: 'var(--geekblue-7)',
                      background: 'var(--geekblue-1)',
                      padding: '4px 8px',
                      borderRadius: 'var(--radius-sm)',
                      overflowWrap: 'anywhere',
                    }}
                  >
                    {JSON.stringify(h.meta)}
                  </code>
                ) : null}
              </div>
            ))}
          </div>
        ) : out.diag?.error ? null : (
          // diag.error면 "회상 없음" 대신 아래 진단 패널이 실패를 말한다(codex 125 M2 — 실패≠0건).
          <div style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>{emptyMessage}</div>
        )
      ) : null}

      {/* 지속 오류(스펙 125) — 토스트는 사라지므로 네트워크/HTTP 실패를 화면에 남긴다. */}
      {errMsg ? <Alert type="error" showIcon title="검색 실패" description={errMsg} /> : null}
      {/* 진단 패널 — 메모리 경로가 diag를 주면 "왜 0건/실패인지"를 지속 표시. */}
      {out?.diag ? <DiagPanel diag={out.diag} /> : null}
    </div>
  )
}
