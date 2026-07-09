import { Input, Select, Button, Segmented } from 'antd'
import type { PipelineNode } from '../../mockData'

/* 노드형 일렬 파이프라인 편집기(스펙 259) — impl=pipeline일 때 "하는 일" 자리에 뜬다.
   ArtifactSpecEditor(190) 관용구 계승: 테두리 카드 + add/remove + per-item 설정 + xxxValid 게이트.
   각 노드 = { 이름 · 프롬프트 · 모델 · 도구 }. 노드를 위→아래 순서대로 이어 실행(일렬).
   - learning 078: 라벨+설명은 세로 스택(형제 flex 폭 다툼 금지) — 프롬프트 라벨 줄에 페르소나 불러오기.
   - beauty=trust: 단계 번호 배지 + 노드 사이 ↓ 연결로 "일렬" 흐름을 시각화.
   - 에이전트-레벨 도구는 숨김(스펙 259 결정 #2) — 도구는 노드가 직접 고르고, 풀은 합집합에서 파생. */
export function NodeListEditor({
  value,
  onChange,
  modelOptions,
  personas,
  toolOptions,
  memoryOptions,
}: {
  value: PipelineNode[] | undefined
  onChange: (nodes: PipelineNode[]) => void
  modelOptions: { label: string; value: string }[]
  personas: { name: string; body: string }[]
  toolOptions: { label: string; value: string }[]
  memoryOptions: { label: string; value: string }[]
}) {
  const nodes = value ?? []
  const update = (next: PipelineNode[]) => onChange(next)
  const setNode = (i: number, patch: Partial<PipelineNode>) =>
    update(nodes.map((n, j) => (j === i ? { ...n, ...patch } : n)))
  const add = () =>
    update([...nodes, { name: '', prompt: '', model: modelOptions[0]?.value ?? '', tools: [], context: 'carry' }])
  const remove = (i: number) => update(nodes.filter((_, j) => j !== i))
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir
    if (j < 0 || j >= nodes.length) return
    const next = [...nodes]
    ;[next[i], next[j]] = [next[j], next[i]]
    update(next)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 12 }}>
        노드를 위에서 아래로 순서대로 이어 실행합니다. 노드마다 프롬프트·모델·참고할 도구를 직접 정합니다.
        앞 노드의 결과가 다음 노드로 전달됩니다.
      </span>
      {nodes.length === 0 && (
        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)', marginBottom: 12 }}>
          아직 노드가 없습니다 — 아래 "노드 추가"로 첫 단계를 만드세요(최소 1개 필요).
        </span>
      )}
      {nodes.map((n, i) => (
        <div key={i} style={{ display: 'flex', flexDirection: 'column' }}>
          {i > 0 && (
            <div style={{ textAlign: 'center', color: 'var(--color-text-quaternary)', fontSize: 14, lineHeight: '18px' }}>
              ↓
            </div>
          )}
          <div
            style={{
              border: '1px solid var(--color-border)',
              borderRadius: 8,
              padding: 12,
              marginTop: i > 0 ? 4 : 0,
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
            }}
          >
            {/* 헤더: 단계 배지 + 이름 + 순서이동 + 삭제 */}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span
                style={{
                  flex: 'none',
                  minWidth: 22,
                  height: 22,
                  padding: '0 6px',
                  borderRadius: 11,
                  background: 'var(--color-fill-tertiary)',
                  color: 'var(--color-text-secondary)',
                  fontSize: 12,
                  fontWeight: 600,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {i + 1}
              </span>
              <Input
                placeholder={`노드 ${i + 1} 이름 (선택 — 예: 분석)`}
                value={n.name}
                onChange={(e) => setNode(i, { name: e.target.value })}
              />
              <Button size="small" type="text" disabled={i === 0} onClick={() => move(i, -1)} title="위로">
                ↑
              </Button>
              <Button size="small" type="text" disabled={i === nodes.length - 1} onClick={() => move(i, 1)} title="아래로">
                ↓
              </Button>
              <Button danger type="text" onClick={() => remove(i)}>
                삭제
              </Button>
            </div>

            {/* 프롬프트(라벨 줄에 페르소나 불러오기 — learning 078: 세로 스택, 형제 폭 다툼 금지) */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>프롬프트</span>
                {personas.length > 0 && (
                  <Select
                    size="small"
                    style={{ width: 200 }}
                    value={undefined}
                    placeholder="등록 페르소나에서 가져오기"
                    options={personas.map((p) => ({ label: p.name, value: p.name }))}
                    onChange={(name) => {
                      const p = personas.find((x) => x.name === name)
                      if (p) setNode(i, { prompt: p.body })
                    }}
                  />
                )}
              </div>
              <Input.TextArea
                placeholder="이 노드가 할 일을 지시하세요 (예: 입력을 분석해 핵심 3가지를 뽑아라)"
                value={n.prompt}
                onChange={(e) => setNode(i, { prompt: e.target.value })}
                autoSize={{ minRows: 3, maxRows: 10 }}
                status={n.prompt.trim() ? undefined : 'error'}
              />
            </div>

            {/* 모델(필수) + 도구(선택) */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 10 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>모델</span>
                <Select
                  value={n.model || undefined}
                  onChange={(v) => setNode(i, { model: v })}
                  options={modelOptions}
                  placeholder="이 노드가 쓸 모델 선택"
                  status={n.model.trim() ? undefined : 'error'}
                  style={{ width: '100%' }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>도구 (선택)</span>
                <Select
                  mode="multiple"
                  allowClear
                  value={n.tools}
                  onChange={(vals) => setNode(i, { tools: vals })}
                  options={toolOptions}
                  placeholder={toolOptions.length ? '이 노드가 참고할 도구' : '등록된 도구·문서 없음'}
                  disabled={toolOptions.length === 0}
                  style={{ width: '100%' }}
                />
              </div>
            </div>

            {/* 받기/내보내기 한 줄(스펙 267 — 사용자 정의 문구): "이전 결과 받기"=이전 노드의 결과를
                어떻게 받을까(260 context), "응답 형식"=이 노드가 어떻게 출력할까(261 format).
                첫 노드에도 받기 노출 — A2A 연계 시 앞 에이전트의 결과가 대화로 들어오므로(사용자 확인). */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 10 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>이전 결과 받기</span>
                <Segmented
                  value={n.context ?? 'carry'}
                  onChange={(v) => setNode(i, { context: v as 'carry' | 'clean' })}
                  options={[
                    { label: '대화 전체와 함께', value: 'carry' },
                    { label: '이전 결과만', value: 'clean' },
                  ]}
                />
                <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                  {(n.context ?? 'carry') === 'clean'
                    ? '앞의 대화는 걷어내고 바로 앞 결과만 받습니다.'
                    : '지금까지의 대화 전체를 보고 처리합니다.'}
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>응답 형식</span>
                <Segmented
                  value={n.format ?? 'text'}
                  onChange={(v) => setNode(i, { format: v as 'text' | 'json' })}
                  options={[
                    { label: '자유 텍스트', value: 'text' },
                    { label: 'JSON', value: 'json' },
                  ]}
                />
                <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                  {(n.format ?? 'text') === 'json'
                    ? 'JSON 객체로만 답하게 강제합니다(어긋나면 1회 교정, 실패 시 원문).'
                    : '모델이 쓰는 대로 내보냅니다.'}
                </span>
              </div>
            </div>
            {(n.format ?? 'text') === 'json' && (
              <Select
                mode="tags"
                allowClear
                value={n.fields ?? []}
                onChange={(vals) => setNode(i, { fields: vals })}
                placeholder="JSON 필수 키 (선택 — 입력 후 Enter, 예: title, summary)"
                options={[]}
                style={{ width: '100%' }}
                tokenSeparators={[',']}
              />
            )}

            {/* 노드별 기억(스펙 268 P2) — 선택하면 이 노드가 회상을 받음. 키워드는 프록시가 캐싱
                (같은 키워드=조회 1회 공유). 기억을 골랐을 때만 키워드 모드 노출(간결 기조 267). */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 10 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>기억 (선택)</span>
                <Select
                  mode="multiple"
                  allowClear
                  value={n.memories ?? []}
                  onChange={(vals) => setNode(i, { memories: vals })}
                  options={memoryOptions}
                  placeholder={memoryOptions.length ? '이 노드가 회상할 기억' : '등록된 기억 없음'}
                  disabled={memoryOptions.length === 0}
                  style={{ width: '100%' }}
                />
              </div>
              {(n.memories?.length ?? 0) > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>회상 키워드</span>
                  <Segmented
                    value={n.memoryQuery ?? 'user'}
                    onChange={(v) => setNode(i, { memoryQuery: v as 'user' | 'input' })}
                    options={[
                      { label: '사용자 입력', value: 'user' },
                      { label: '이 노드의 입력', value: 'input' },
                    ]}
                  />
                  <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                    {(n.memoryQuery ?? 'user') === 'input'
                      ? '이 노드가 받은 내용으로 기억을 찾습니다.'
                      : '사용자 질문으로 기억을 찾습니다(다른 노드와 조회 공유).'}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      ))}
      <Button onClick={add} style={{ alignSelf: 'flex-start', marginTop: nodes.length ? 12 : 0 }}>
        + 노드 추가
      </Button>
    </div>
  )
}

/* 저장 가능한 최소 조건(스펙 259) — 노드 ≥1, 각 노드 프롬프트+모델 채움. 폼 스텝/저장 게이트가 소비. */
export function pipelineValid(nodes: PipelineNode[] | undefined): boolean {
  return !!nodes?.length && nodes.every((n) => n.prompt.trim() !== '' && n.model.trim() !== '')
}
