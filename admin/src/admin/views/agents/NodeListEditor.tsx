import { Input, Select, Button, Segmented } from 'antd'
import type { PipelineNode } from '../../mockData'
import { ShortTermMemoryField, LongTermMemoryField } from './MemoryFields'
import { ModelField, chatModelOptions } from './ModelFields'
import { PromptField } from './PromptFields'

/* 노드형 일렬 파이프라인 편집기(스펙 259) — impl=pipeline일 때 "하는 일" 자리에 뜬다.
   ArtifactSpecEditor(190) 관용구 계승: 테두리 카드 + add/remove + per-item 설정 + xxxValid 게이트.
   각 노드 = { 이름 · 프롬프트 · 모델 · 도구 }. 노드를 위→아래 순서대로 이어 실행(일렬).
   - learning 078: 라벨+설명은 세로 스택(형제 flex 폭 다툼 금지) — 프롬프트 라벨 줄에 페르소나 불러오기.
   - beauty=trust: 단계 번호 배지 + 노드 사이 ↓ 연결로 "일렬" 흐름을 시각화.
   - 에이전트-레벨 도구는 숨김(스펙 259 결정 #2) — 도구는 노드가 직접 고르고, 풀은 합집합에서 파생. */
// 문서 검색 도구 판별(스펙 272) — 노드 tools에 컬렉션은 search_documents__<컬렉션>(268 P1)으로 저장.
// 구저장 민이름(search_documents=전체 컬렉션)도 문서로 인식(무회귀). 그 외는 MCP 도구(server__tool).
//
// ⚠ 예약 이름공간 불변식(codex 272 High=측정상 도달불가 확인, 243 ① "파생 id는 이름공간 예약"):
// MCP 런타임명=safeToolName(server,tool)=`server__tool`인데, server가 'search_documents'면 충돌한다.
// 그러나 (a) NAME_RULE(naming.ts·서버 naming.py)이 **밑줄 금지**(영소문자·숫자·대시만)라 이름
// 'search_documents'(밑줄)는 생성 불가, (b) safeToolName은 **대시를 보존**하므로 유효명
// 'search-documents'→'search-documents__…'(대시)라 이 접두에 안 걸린다. 두 보증이 충돌을 원천 차단.
// **NAME_RULE에 밑줄을 허용하게 바꾸면 이 불변식이 깨지므로 여기 isDocTool을 재검토할 것.**
const isDocTool = (t: string) => t === 'search_documents' || t.startsWith('search_documents__')

export function NodeListEditor({
  value,
  onChange,
  models,
  personas,
  mcpOptions,
  docOptions,
  memoryOptions,
}: {
  value: PipelineNode[] | undefined
  onChange: (nodes: PipelineNode[]) => void
  models: { name: string; kind: string }[] // 등록 모델(필터·옵션화는 공용 ModelField가, 스펙 274)
  personas: { name: string; body: string }[]
  mcpOptions: { label: string; value: string }[] // MCP 도구(server__tool)
  docOptions: { label: string; value: string }[] // 문서 컬렉션(search_documents__<col>)
  memoryOptions: { label: string; value: string }[]
}) {
  const nodes = value ?? []
  const update = (next: PipelineNode[]) => onChange(next)
  const setNode = (i: number, patch: Partial<PipelineNode>) =>
    update(nodes.map((n, j) => (j === i ? { ...n, ...patch } : n)))
  const add = () =>
    update([...nodes, { name: '', prompt: '', model: chatModelOptions(models)[0]?.value ?? '', tools: [], context: 'carry' }])
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

            {/* 카드 배치(사용자 지시 2026-07-10): 프롬프트 → 모델 → 기억(단기·장기) → 도구·문서 →
                받기·형식. 프롬프트·모델·기억은 공용 컨트롤(스펙 271/274 — 라벨·옵션·가드 단일 출처). */}
            <PromptField
              label="프롬프트"
              value={n.prompt}
              onChange={(v) => setNode(i, { prompt: v })}
              personas={personas}
              placeholder="이 노드가 할 일을 지시하세요 (예: 입력을 분석해 핵심 3가지를 뽑아라)"
              required
            />
            <ModelField
              value={n.model}
              onChange={(v) => setNode(i, { model: v })}
              models={models}
              placeholder="이 노드가 쓸 모델 선택"
              required
            />

            {/* 기억(단기+장기) — 에이전트 폼 기억 구획(271)과 같은 나란히 배치.
                단기는 "이전 결과만"(clean)이면 대화를 안 보므로 비활성(270 결정 (가)). */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 10 }}>
              <ShortTermMemoryField
                value={n.historyDepth}
                onChange={(v) => setNode(i, { historyDepth: v })}
                allowInherit
                disabled={(n.context ?? 'carry') === 'clean'}
                hint={(n.context ?? 'carry') === 'clean'
                  ? '"이전 결과만"이라 이전 대화를 보지 않습니다.'
                  : '이 노드가 볼 이전 대화 턴 수(상속=에이전트 설정).'}
              />
              <LongTermMemoryField
                value={n.memories ?? []}
                onChange={(vals) => setNode(i, { memories: vals })}
                options={memoryOptions}
                queryMode={n.memoryQuery ?? 'user'}
                onQueryModeChange={(v) => setNode(i, { memoryQuery: v })}
              />
            </div>

            {/* 도구·문서 나란히 — 둘 다 n.tools 한 배열을 나눠 소비, 변경 시 상대 항목 보존(스펙 272 병합). */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 10 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>도구 (선택)</span>
                <Select
                  mode="multiple"
                  allowClear
                  value={n.tools.filter((t) => !isDocTool(t))}
                  onChange={(vals) => setNode(i, { tools: [...vals, ...n.tools.filter(isDocTool)] })}
                  options={mcpOptions}
                  placeholder={mcpOptions.length ? '이 노드가 쓸 MCP 도구' : '등록된 MCP 도구 없음'}
                  disabled={mcpOptions.length === 0}
                  style={{ width: '100%' }}
                />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>문서 (선택)</span>
                <Select
                  mode="multiple"
                  allowClear
                  value={n.tools.filter(isDocTool)}
                  onChange={(vals) => setNode(i, { tools: [...n.tools.filter((t) => !isDocTool(t)), ...vals] })}
                  options={docOptions}
                  placeholder={docOptions.length ? '이 노드가 검색할 문서 컬렉션' : '등록된 컬렉션 없음'}
                  disabled={docOptions.length === 0}
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
