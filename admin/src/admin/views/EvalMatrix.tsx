/* my-agents admin — 모델 격자 뷰 (스펙 141, promptfoo matrix 문법).
   행=문제, 열=모델(같은 비교 그룹의 런), 셀=통과/실패(+점수 툴팁, 클릭→성적표).
   "다른 결과만" 필터 = promptfoo Different(모델 간 결과가 갈리는 행만 — 모델 선정의 신호는 거기 있다). */
import { useEffect, useMemo, useState } from 'react'
import { Select, Tag, Switch, Tooltip, Alert, message, Table } from 'antd'
import { Icon } from '../icons'
import { getEvalRun, listEvalRunsByGroup, type EvalRunT, type EvalRunDetail } from '../../api'

const fmtTime = (s?: string | null) => (s ? s.slice(5, 16).replace('T', ' ') : '—')

interface GroupInfo {
  groupId: string
  datasetName: string
  agentName: string
  startedAt: string
  runs: EvalRunT[] // 그룹 내 런들(모델별)
}

export function MatrixView({ runs, onOpenRun }: { runs: EvalRunT[]; onOpenRun: (id: string) => void }) {
  const groups = useMemo<GroupInfo[]>(() => {
    const byGroup = new Map<string, EvalRunT[]>()
    for (const r of runs) {
      if (!r.group_id) continue
      const arr = byGroup.get(r.group_id) ?? []
      arr.push(r)
      byGroup.set(r.group_id, arr)
    }
    return [...byGroup.entries()]
      .map(([gid, rs]) => ({
        groupId: gid,
        datasetName: rs[0].dataset_name ?? '—',
        agentName: rs[0].agent_name ?? '—',
        startedAt: rs[rs.length - 1].started_at, // 목록은 최신순 → 마지막이 그룹 시작
        runs: rs.slice().reverse(), // 실행 순서(모델 지정 순)로
      }))
      .sort((a, b) => (a.startedAt < b.startedAt ? 1 : -1))
  }, [runs])

  const [groupId, setGroupId] = useState<string | undefined>()
  const [details, setDetails] = useState<EvalRunDetail[]>([])
  const [diffOnly, setDiffOnly] = useState(false)
  const group = groups.find((g) => g.groupId === groupId) ?? groups[0]

  useEffect(() => {
    setDetails([])
    if (!group) return
    let alive = true
    // 그룹 전량을 서버에서 재조회(codex 141 #1) — 최근 50 컷에 그룹이 걸치면 부분 격자가 되므로
    // 목록의 runs를 신뢰하지 않고 group_id로 완전한 그룹을 받아온다.
    listEvalRunsByGroup(group.groupId)
      .then((full) => Promise.all(full.slice().reverse().map((r) => getEvalRun(r.id))))
      .then((ds) => alive && setDetails(ds))
      .catch((e) => message.error((e as Error).message))
    return () => {
      alive = false
    }
  }, [group?.groupId, group?.runs.map((r) => r.status).join()])

  if (groups.length === 0) {
    return (
      <Alert
        type="info"
        showIcon
        title="비교 그룹이 없습니다"
        description="문제집 드로어에서 모델을 2개 이상 선택해 실행하면 여기서 모델별 결과를 격자로 비교할 수 있습니다."
      />
    )
  }

  // 행=케이스(첫 런의 순서 기준, 합집합), 열=모델
  const caseNames = [...new Set(details.flatMap((d) => d.results.map((r) => r.case_name)))]
  const cellOf = (d: EvalRunDetail, name: string) => d.results.find((r) => r.case_name === name)
  const rows = caseNames
    .map((name) => ({ name, cells: details.map((d) => cellOf(d, name)) }))
    .filter((row) => {
      if (!diffOnly) return true
      const vals = row.cells.map((c) => (c === undefined ? 'none' : c.case_passed ? 'pass' : 'fail'))
      return new Set(vals).size > 1
    })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <Select
          style={{ minWidth: 300 }}
          value={group?.groupId}
          onChange={setGroupId}
          options={groups.map((g) => ({
            value: g.groupId,
            label: `${fmtTime(g.startedAt)} · ${g.datasetName} · ${g.agentName} · 모델 ${g.runs.length}개`,
          }))}
        />
        <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 13 }}>
          <Switch size="small" checked={diffOnly} onChange={setDiffOnly} />
          다른 결과만
        </span>
      </div>

      {/* antd Table로 통일(스펙 204) — 생 HTML table 제거. 열=모델(동적 컬럼), 합계=Summary 행,
          가로 스크롤은 Table scroll.x가 담당(수제 overflowX 래퍼 제거). */}
      {details.length > 0 ? (
        <Table
          size="small"
          pagination={false}
          scroll={{ x: 'max-content' }}
          rowKey={(row) => row.name}
          dataSource={rows}
          columns={[
            {
              title: '문제',
              dataIndex: 'name',
              render: (v: string) => (
                <span style={{ fontSize: 13, maxWidth: 280, display: 'inline-block', overflowWrap: 'anywhere' }}>{v}</span>
              ),
            },
            ...details.map((d, i) => ({
              title: <span style={{ whiteSpace: 'nowrap' as const }}>{d.model_name ?? '(기본 모델)'}</span>,
              align: 'center' as const,
              render: (_: unknown, row: (typeof rows)[number]) => {
                const c = row.cells[i]
                return (
                  <span onClick={() => onOpenRun(details[i].id)} style={{ cursor: 'pointer' }}>
                    {c === undefined ? (
                      <Tag>—</Tag>
                    ) : (
                      <Tooltip title={`${c.details.filter(([, ok]: [string, boolean]) => ok).length}/${c.details.length} 기준 통과 — 클릭하면 성적표`}>
                        <Tag color={c.case_passed ? 'green' : 'red'} style={{ margin: 0 }}>
                          {c.case_passed ? '통과' : '실패'}
                        </Tag>
                      </Tooltip>
                    )}
                  </span>
                )
              },
            })),
          ]}
          summary={() => (
            <Table.Summary.Row>
              <Table.Summary.Cell index={0}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>합계</span>
              </Table.Summary.Cell>
              {details.map((d, i) => (
                <Table.Summary.Cell key={d.id} index={i + 1} align="center">
                  {d.status === 'running' ? (
                    <span style={{ display: 'inline-flex', gap: 5, alignItems: 'center' }}>
                      <Icon name="loading" spin size={12} /> 실행 중
                    </span>
                  ) : d.status === 'error' ? (
                    <Tag color="red" style={{ margin: 0 }}>error</Tag>
                  ) : (
                    <span style={{ fontWeight: 600, fontSize: 13 }}>
                      {`${d.score != null ? Math.round(d.score * 100) : '—'}% (${d.passed}/${d.total})`}
                    </span>
                  )}
                </Table.Summary.Cell>
              ))}
            </Table.Summary.Row>
          )}
        />
      ) : (
        <div style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>불러오는 중…</div>
      )}
      {diffOnly && rows.length === 0 && details.length > 0 ? (
        <Alert type="success" showIcon title="모든 문제에서 모델 간 결과가 같습니다." />
      ) : null}
    </div>
  )
}
