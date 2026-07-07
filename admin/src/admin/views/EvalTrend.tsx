/* my-agents admin — 평가 성적 추이 차트 + 런 비교 드로어 (스펙 138, dataviz 스킬 적용).
   추이: 단일 계열(범례 불요) 라인+점, 프라이머리 블루(검증기 PASS), y 0~100%, 점 호버 툴팁,
   마지막 점만 직접 라벨(선택적 라벨링). error 런은 차트 제외(목록에 상태 태그로).
   비교: 케이스별 A→B 변화 — 회귀(red)+아이콘·개선(green)+아이콘(색 단독 금지), 회귀 우선 정렬. */
import { useEffect, useMemo, useState } from 'react'
import { Tag, Tooltip, Alert, message, Collapse } from 'antd'
import { Drawer } from '../shared'
import { Icon } from '../icons'
import { getEvalRun, type EvalRunT, type EvalRunDetail } from '../../api'

const fmtTime = (s?: string | null) => (s ? s.slice(5, 16).replace('T', ' ') : '—')

/** 성적 추이 미니 차트 — runs는 최신순 입력을 받아 내부에서 시간순으로 뒤집는다. */
export function TrendChart({ runs }: { runs: EvalRunT[] }) {
  const pts = useMemo(
    () => runs.filter((r) => r.status === 'ok' && r.score != null).slice().reverse(),
    [runs]
  )
  if (pts.length < 2) {
    return (
      <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', padding: '8px 0' }}>
        {pts.length === 1
          ? `최근 점수 ${Math.round((pts[0].score ?? 0) * 100)}% — 런이 2개 이상이면 추이가 그려집니다.`
          : '완료된 런이 생기면 추이가 그려집니다.'}
      </div>
    )
  }
  const W = 560
  const H = 84
  const padL = 34
  const padR = 44 // 마지막 점 직접 라벨 공간
  const padY = 12
  const x = (i: number) => padL + (i * (W - padL - padR)) / (pts.length - 1)
  const y = (score: number) => H - padY - score * (H - 2 * padY)
  const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(p.score ?? 0)}`).join(' ')
  const last = pts[pts.length - 1]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} role="img" aria-label="성적 추이">
      {/* 은은한 그리드(0/50/100%) — 눈금은 보조, 데이터가 주인공. */}
      {[0, 0.5, 1].map((g) => (
        <g key={g}>
          <line x1={padL} x2={W - padR} y1={y(g)} y2={y(g)} stroke="var(--color-border-secondary)" strokeDasharray="3 4" strokeWidth={1} />
          <text x={padL - 6} y={y(g) + 4} textAnchor="end" fontSize={10} fill="var(--color-text-tertiary)">
            {Math.round(g * 100)}
          </text>
        </g>
      ))}
      <path d={path} fill="none" stroke="var(--color-primary)" strokeWidth={2} strokeLinejoin="round" />
      {pts.map((p, i) => (
        <Tooltip key={p.id} title={`${fmtTime(p.started_at)} · ${Math.round((p.score ?? 0) * 100)}% (${p.passed}/${p.total})`}>
          {/* 8px 점 + 2px 표면 링(겹침 분리) — 히트 영역은 투명 원으로 점보다 크게. */}
          <g style={{ cursor: 'default' }}>
            <circle cx={x(i)} cy={y(p.score ?? 0)} r={10} fill="transparent" />
            <circle cx={x(i)} cy={y(p.score ?? 0)} r={4} fill="var(--color-primary)" stroke="var(--color-bg-container)" strokeWidth={2} />
          </g>
        </Tooltip>
      ))}
      {/* 마지막 점만 직접 라벨(현재 점수) — 텍스트는 텍스트 토큰(계열색 금지). */}
      <text x={x(pts.length - 1) + 8} y={y(last.score ?? 0) + 4} fontSize={12} fontWeight={600} fill="var(--color-text-heading)">
        {Math.round((last.score ?? 0) * 100)}%
      </text>
    </svg>
  )
}

/** 두 런 비교 드로어 — A(이전)→B(이후), 회귀 우선 정렬 + assert 단위 diff. */
export function CompareDrawer({ aId, bId, onClose }: { aId: string | null; bId: string | null; onClose: () => void }) {
  const [a, setA] = useState<EvalRunDetail | null>(null)
  const [b, setB] = useState<EvalRunDetail | null>(null)

  useEffect(() => {
    setA(null)
    setB(null)
    if (!aId || !bId) return
    let alive = true
    Promise.all([getEvalRun(aId), getEvalRun(bId)])
      .then(([ra, rb]) => {
        if (!alive) return
        // A=이전, B=이후로 정렬(시작 시각 기준) — "무엇이 변했나"의 방향 고정.
        const [first, second] = ra.started_at <= rb.started_at ? [ra, rb] : [rb, ra]
        setA(first)
        setB(second)
      })
      .catch((e) => message.error((e as Error).message))
    return () => {
      alive = false
    }
  }, [aId, bId])

  const rows = useMemo(() => {
    if (!a || !b) return []
    const byName = (d: EvalRunDetail) => new Map(d.results.map((r) => [r.case_name, r]))
    const am = byName(a)
    const bm = byName(b)
    const names = [...new Set([...am.keys(), ...bm.keys()])]
    const kind = (n: string) => {
      const pa = am.get(n)?.case_passed
      const pb = bm.get(n)?.case_passed
      if (pa === true && pb === false) return 'regress'
      if (pa === false && pb === true) return 'improve'
      if (pa === undefined || pb === undefined) return 'only-one'
      return 'same'
    }
    const order = { regress: 0, improve: 1, 'only-one': 2, same: 3 } as const
    return names
      .map((n) => ({ name: n, a: am.get(n), b: bm.get(n), kind: kind(n) }))
      .sort((x, y) => order[x.kind as keyof typeof order] - order[y.kind as keyof typeof order])
  }, [a, b])

  const pct = (d: EvalRunDetail | null) => (d?.score != null ? Math.round(d.score * 100) : null)
  const delta = a && b && pct(a) != null && pct(b) != null ? (pct(b) as number) - (pct(a) as number) : null
  const regressCount = rows.filter((r) => r.kind === 'regress').length

  return (
    <Drawer open={!!(aId && bId)} width={640} title="런 비교 (이전 → 이후)" onClose={onClose}>
      {a && b ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 24, fontWeight: 700 }}>
              {pct(a)}% → {pct(b)}%
            </span>
            {delta != null && delta !== 0 ? (
              <Tag color={delta < 0 ? 'red' : 'green'} style={{ fontSize: 13 }}>
                <Icon name={delta < 0 ? 'close-circle' : 'check-circle'} size={11} /> {delta > 0 ? '+' : ''}
                {delta}%p
              </Tag>
            ) : (
              <Tag>변화 없음</Tag>
            )}
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              {fmtTime(a.started_at)} → {fmtTime(b.started_at)} · {a.agent_name}
              {a.agent_name !== b.agent_name ? ` → ${b.agent_name}` : ''}
            </span>
          </div>
          {regressCount > 0 ? (
            <Alert type="error" showIcon title={`회귀 ${regressCount}건 — 이전엔 통과했는데 이번에 실패한 문제가 있습니다.`} />
          ) : null}
          {/* 공통 문제 부족 경고(codex 138 #2) — 비교는 문제 이름으로 매칭하므로 개명되면 A/B가 아님. */}
          {rows.length > 0 && rows.every((r) => r.kind === 'only-one') ? (
            <Alert type="warning" showIcon title="두 런에 공통 문제가 없습니다 — 문제 이름이 바뀌었을 수 있어 점수 비교만 유효합니다(문제별 비교 불가)." />
          ) : null}

          {/* antd Collapse(accordion)로 통일(스펙 204) — 수제 onClick div+회전 셰브론+open 상태 제거. */}
          <Collapse
            accordion
            items={rows.map((r) => {
              const tag =
                r.kind === 'regress' ? (
                  <Tag color="red"><Icon name="close-circle" size={11} /> 회귀</Tag>
                ) : r.kind === 'improve' ? (
                  <Tag color="green"><Icon name="check-circle" size={11} /> 개선</Tag>
                ) : r.kind === 'only-one' ? (
                  <Tag color="gold">한쪽에만 존재</Tag>
                ) : (
                  <Tag>동일</Tag>
                )
              const cell = (res?: { case_passed: boolean }) =>
                res === undefined ? <Tag>—</Tag> : res.case_passed ? <Tag color="green">통과</Tag> : <Tag color="red">실패</Tag>
              // assert 단위 diff — 이름 합집합, 새로 실패(a true→b false)를 붉게.
              const aDet = new Map((r.a?.details ?? []).map(([n, ok]) => [n, ok]))
              const bDet = new Map((r.b?.details ?? []).map(([n, ok]) => [n, ok]))
              const assertNames = [...new Set([...aDet.keys(), ...bDet.keys()])]
              return {
                key: r.name,
                label: (
                  <span style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {tag}
                    <span style={{ fontWeight: 600, flex: 1, minWidth: 120 }}>{r.name}</span>
                    <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>이전</span>
                    {cell(r.a)}
                    <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>이후</span>
                    {cell(r.b)}
                  </span>
                ),
                children: (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
                    {assertNames.map((n) => {
                      const oa = aDet.get(n)
                      const ob = bDet.get(n)
                      const newlyFailed = oa === true && ob === false
                      return (
                        <div key={n} style={{ display: 'flex', gap: 8, alignItems: 'center', color: newlyFailed ? 'var(--color-error)' : undefined }}>
                          <span style={{ fontFamily: 'var(--font-family-code)', flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{n}</span>
                          <Icon name={oa ? 'check-circle' : 'close-circle'} size={12} style={{ color: oa ? 'var(--color-success)' : 'var(--color-error)', opacity: oa === undefined ? 0.2 : 1 }} />
                          <Icon name="right" size={10} style={{ color: 'var(--color-text-tertiary)' }} />
                          <Icon name={ob ? 'check-circle' : 'close-circle'} size={12} style={{ color: ob ? 'var(--color-success)' : 'var(--color-error)', opacity: ob === undefined ? 0.2 : 1 }} />
                          {newlyFailed ? (
                            <Tag color="red">새로 실패</Tag>
                          ) : oa === undefined && ob === false ? (
                            // 런 A 이후 추가된 기준이 실패 — "기존 기준이 깨짐"과 구분(138 e2e T7).
                            <Tag color="orange">신규 기준 · 실패</Tag>
                          ) : null}
                        </div>
                      )
                    })}
                  </div>
                ),
              }
            })}
          />
        </div>
      ) : (
        <div style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>불러오는 중…</div>
      )}
    </Drawer>
  )
}
