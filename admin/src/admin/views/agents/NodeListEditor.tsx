import { useEffect, useState } from 'react'
import { Input, Select, Button, Segmented, Collapse, Tag, Descriptions } from 'antd'
import { isNodeRef, type PipelineNode, type PipelineNodeRef } from '../../mockData'
import {
  listNodeTemplates,
  getNodeTemplate,
  type NodeTemplateGroup,
  type NodeTemplateDetail,
} from '../../../api'
import { ShortTermMemoryField, LongTermMemoryField } from './MemoryFields'
import { ModelField, chatModelOptions } from './ModelFields'
import { PromptField } from './PromptFields'
import { ToolTree } from './ToolTree'

/* 노드형 일렬 파이프라인 편집기(스펙 259) — impl=pipeline일 때 "하는 일" 자리에 뜬다.
   ArtifactSpecEditor(190) 관용구 계승: 테두리 카드 + add/remove + per-item 설정 + xxxValid 게이트.
   각 노드 = { 이름 · 프롬프트 · 모델 · 도구 } 인라인 설정 **또는** 노드 라이브러리 참조(스펙 316,
   {ref:{name,version}} — 버전 핀 고정). 노드를 위→아래 순서대로 이어 실행(일렬).
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

/* 받기(context)·형식(format) 사용자 라벨 — 편집 Segmented와 읽기 전용 요약(참조 미리보기·노드
   라이브러리 상세)이 같은 문구를 쓴다(스펙 316, 단일 출처). */
export const NODE_CONTEXT_LABEL: Record<'carry' | 'clean', string> = {
  carry: '대화 전체와 함께',
  clean: '이전 결과만',
}
export const NODE_FORMAT_LABEL: Record<'text' | 'json', string> = {
  text: '자유 텍스트',
  json: 'JSON',
}

/* 노드 설정 요약(스펙 316, 읽기 전용) — 참조 노드 미리보기(에이전트 폼)와 노드 라이브러리 버전
   상세가 공유하는 단일 렌더러. "무엇이 실행되는지 가리지 않음"(beauty=trust) — 프롬프트 앞부분·
   모델·도구·받기/형식·기억을 보여준다. */
export function NodeConfigSummary({ config }: { config: PipelineNode }) {
  const prompt = (config.prompt ?? '').trim()
  return (
    <Descriptions
      column={1}
      size="small"
      items={[
        {
          key: 'prompt',
          label: '프롬프트',
          children: (
            <span style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 13 }}>
              {prompt ? prompt.slice(0, 160) + (prompt.length > 160 ? '…' : '') : '—'}
            </span>
          ),
        },
        {
          key: 'model',
          label: '모델',
          children: config.model ? (
            <code style={{ fontFamily: 'var(--font-family-code)', fontSize: 13 }}>{config.model}</code>
          ) : (
            '—'
          ),
        },
        {
          key: 'tools',
          label: `도구 ${(config.tools ?? []).length}개`,
          children: (config.tools ?? []).length ? (
            <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
              {(config.tools ?? []).map((t) => (
                <Tag key={t} style={{ margin: 0 }}>
                  {t}
                </Tag>
              ))}
            </span>
          ) : (
            '없음'
          ),
        },
        {
          key: 'flow',
          label: '받기 · 형식',
          children: `${NODE_CONTEXT_LABEL[config.context ?? 'carry']} · ${NODE_FORMAT_LABEL[config.format ?? 'text']}`,
        },
        ...((config.memories ?? []).length
          ? [{ key: 'mem', label: '기억', children: (config.memories ?? []).join(', ') }]
          : []),
      ]}
    />
  )
}

/* 노드 한 개의 설정 필드(스펙 316에서 추출) — NodeListEditor 카드 본문과 노드 라이브러리 등록/발행
   폼이 **같은** 필드 구성(프롬프트→모델→기억→도구·문서→받기·형식)을 조립한다(단일 출처, 드리프트 0).
   카드 배치(사용자 지시 2026-07-10): 프롬프트 → 모델 → 기억(단기·장기) → 도구·문서 → 받기·형식. */
export function NodeConfigFields({
  value: n,
  onChange,
  models,
  personas,
  mcpServers,
  docOptions,
  memoryOptions,
}: {
  value: PipelineNode
  onChange: (patch: Partial<PipelineNode>) => void
  models: { name: string; kind: string }[]
  personas: { name: string; body: string }[]
  mcpServers: { name: string; tools?: string[] }[]
  docOptions: { label: string; value: string }[]
  memoryOptions: { label: string; value: string }[]
}) {
  // 템플릿/해석 config는 선택 필드(tools 등)를 생략할 수 있다(서버 화이트리스트가 미지정 키를
  // 저장하지 않음, 스펙 316) — 폼 편집 전에 방어 기본값(undefined.filter 크래시 봉인).
  const tools = n.tools ?? []
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* 프롬프트·모델·기억은 공용 컨트롤(스펙 271/274 — 라벨·옵션·가드 단일 출처). */}
      <PromptField
        label="프롬프트"
        value={n.prompt}
        onChange={(v) => onChange({ prompt: v })}
        personas={personas}
        placeholder="이 노드가 할 일을 지시하세요 (예: 입력을 분석해 핵심 3가지를 뽑아라)"
        required
      />
      <ModelField
        value={n.model}
        onChange={(v) => onChange({ model: v })}
        models={models}
        placeholder="이 노드가 쓸 모델 선택"
        required
      />

      {/* 기억(단기+장기) — 에이전트 폼 기억 구획(271)과 같은 나란히 배치.
          단기는 "이전 결과만"(clean)이면 대화를 안 보므로 비활성(270 결정 (가)). */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 10 }}>
        <ShortTermMemoryField
          value={n.historyDepth}
          onChange={(v) => onChange({ historyDepth: v })}
          allowInherit
          disabled={(n.context ?? 'carry') === 'clean'}
          hint={(n.context ?? 'carry') === 'clean'
            ? '"이전 결과만"이라 이전 대화를 보지 않습니다.'
            : '이 노드가 볼 이전 대화 턴 수(상속=에이전트 설정).'}
        />
        <LongTermMemoryField
          value={n.memories ?? []}
          onChange={(vals) => onChange({ memories: vals })}
          options={memoryOptions}
          queryMode={n.memoryQuery ?? 'user'}
          onQueryModeChange={(v) => onChange({ memoryQuery: v })}
        />
      </div>

      {/* 도구=서버→도구 계층 트리(스펙 277) — 문서 항목은 보존해 합쳐 저장(스펙 272 병합). */}
      <ToolTree
        servers={mcpServers}
        value={tools.filter((t) => !isDocTool(t))}
        onChange={(vals) => onChange({ tools: [...vals, ...tools.filter(isDocTool)] })}
      />
      {/* 문서(RAG 컬렉션) — 평면 카탈로그라 트리 아님. 변경 시 도구 항목 보존(스펙 272 병합). */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>문서 (선택)</span>
        <Select
          mode="multiple"
          allowClear
          value={tools.filter(isDocTool)}
          onChange={(vals) => onChange({ tools: [...tools.filter((t) => !isDocTool(t)), ...vals] })}
          options={docOptions}
          placeholder={docOptions.length ? '이 노드가 검색할 문서 컬렉션' : '등록된 컬렉션 없음'}
          disabled={docOptions.length === 0}
          style={{ width: '100%' }}
        />
      </div>

      {/* 받기/내보내기 한 줄(스펙 267 — 사용자 정의 문구): "이전 결과 받기"=이전 노드의 결과를
          어떻게 받을까(260 context), "응답 형식"=이 노드가 어떻게 출력할까(261 format).
          첫 노드에도 받기 노출 — A2A 연계 시 앞 에이전트의 결과가 대화로 들어오므로(사용자 확인). */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 10 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>이전 결과 받기</span>
          <Segmented
            value={n.context ?? 'carry'}
            onChange={(v) => onChange({ context: v as 'carry' | 'clean' })}
            options={[
              { label: NODE_CONTEXT_LABEL.carry, value: 'carry' },
              { label: NODE_CONTEXT_LABEL.clean, value: 'clean' },
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
            onChange={(v) => onChange({ format: v as 'text' | 'json' })}
            options={[
              { label: NODE_FORMAT_LABEL.text, value: 'text' },
              { label: NODE_FORMAT_LABEL.json, value: 'json' },
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
          onChange={(vals) => onChange({ fields: vals })}
          placeholder="JSON 필수 키 (선택 — 입력 후 Enter, 예: title, summary)"
          options={[]}
          style={{ width: '100%' }}
          tokenSeparators={[',']}
        />
      )}
    </div>
  )
}

export function NodeListEditor({
  value,
  onChange,
  models,
  personas,
  mcpServers,
  docOptions,
  memoryOptions,
  fixedStructure = false,
}: {
  value: (PipelineNode | PipelineNodeRef)[] | undefined
  onChange: (nodes: (PipelineNode | PipelineNodeRef)[]) => void
  models: { name: string; kind: string }[] // 등록 모델(필터·옵션화는 공용 ModelField가, 스펙 274)
  personas: { name: string; body: string }[]
  mcpServers: { name: string; tools?: string[] }[] // MCP 서버 카탈로그(ToolTree용, 스펙 277)
  docOptions: { label: string; value: string }[] // 문서 컬렉션(search_documents__<col>)
  memoryOptions: { label: string; value: string }[]
  /** 구조 불변 모드(스펙 287, 오버라이드용) — 추가/삭제/이동 숨김·이름 읽기 전용. 필드만 편집.
      서버도 같은 규칙을 강제(길이 일치 merge)하므로 이 prop은 UX일 뿐 보안 경계가 아니다.
      오버라이드 베이스는 해석된(resolvedNodes) 인라인 노드라 참조 항목이 들어오지 않는다(스펙 316). */
  fixedStructure?: boolean
}) {
  const nodes = value ?? []
  const update = (next: (PipelineNode | PipelineNodeRef)[]) => onChange(next)
  // 인라인 노드 필드 패치 — 참조 항목엔 적용 불가(isNodeRef 가드, 스펙 316).
  const setNode = (i: number, patch: Partial<PipelineNode>) =>
    update(nodes.map((x, j) => (j === i && !isNodeRef(x) ? { ...x, ...patch } : x)))
  // 항목 통째 교체(스펙 316) — 직접↔참조 모드 전환과 참조 대상(name/version) 변경용.
  const replaceNode = (i: number, node: PipelineNode | PipelineNodeRef) =>
    update(nodes.map((x, j) => (j === i ? node : x)))
  const blankInline = (): PipelineNode => ({
    name: '',
    prompt: '',
    model: chatModelOptions(models)[0]?.value ?? '',
    tools: [],
    context: 'carry',
  })
  // 펼침 상태(스펙 275) — UI 로컬(저장 무관), 인덱스 키. 기본 전부 접힘(개요 우선),
  // 노드 추가 시 그 노드만 펼침(작성 동선). 이동/삭제 시 키 재매핑.
  const [open, setOpen] = useState<number[]>([])
  const add = () => {
    setOpen((o) => [...o, nodes.length])
    update([...nodes, blankInline()])
  }
  const remove = (i: number) => {
    setOpen((o) => o.filter((k) => k !== i).map((k) => (k > i ? k - 1 : k)))
    update(nodes.filter((_, j) => j !== i))
  }
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir
    if (j < 0 || j >= nodes.length) return
    setOpen((o) => o.map((k) => (k === i ? j : k === j ? i : k)))
    const next = [...nodes]
    ;[next[i], next[j]] = [next[j], next[i]]
    update(next)
  }

  /* 노드 라이브러리 카탈로그(스펙 316) — 참조 모드 선택지. 저작 화면에서만 로드(오버라이드
     fixedStructure는 해석된 인라인만 받아 참조 UI가 없다). 상세(버전 목록·config)는 이름당 1회 캐시. */
  const [templates, setTemplates] = useState<NodeTemplateGroup[] | null>(null)
  const [details, setDetails] = useState<Record<string, NodeTemplateDetail>>({})
  useEffect(() => {
    if (fixedStructure) return
    listNodeTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([])) // 로드 실패=빈 카탈로그(참조 선택만 못 함 — 인라인 저작은 무영향)
  }, [fixedStructure])
  const loadDetail = (name: string) => {
    if (!name || details[name]) return
    // 실패는 조용히 — 미리보기만 비고, 저장 게이트(pipelineValid)는 name+version으로 독립 판정.
    getNodeTemplate(name)
      .then((d) => setDetails((cur) => ({ ...cur, [name]: d })))
      .catch(() => {})
  }
  // 기존 저장분의 참조 노드 상세 로드 — 편집 재진입 시 버전 옵션·미리보기를 채운다.
  useEffect(() => {
    if (fixedStructure) return
    nodes.filter(isNodeRef).forEach((n) => loadDetail(n.ref.name))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, fixedStructure])

  // 접힘 헤더(스펙 275→287 후속) — 프롬프트 발췌만. 모델·도구 수 등 설정 나열은 노이즈라 뺐다
  // (2026-07-10 지시). 설정은 펼쳐서 보고, 미완성은 "작성 필요" Tag가 알린다.
  // 참조 노드(스펙 316)는 name+version 선택이 곧 완성 조건.
  const nodeInvalid = (n: PipelineNode | PipelineNodeRef) =>
    isNodeRef(n) ? !n.ref.name.trim() || n.ref.version < 1 : !n.prompt.trim() || !n.model.trim()
  const refLabel = (n: PipelineNodeRef) =>
    n.ref.name.trim() ? `${n.ref.name} · v${n.ref.version >= 1 ? n.ref.version : '?'}` : '참조 노드 선택 필요'

  /* 참조 모드 본문(스펙 316) — 이름 Select(카탈로그) → 버전 Select(기본=최신) → 해석 config
     읽기 전용 미리보기(무엇이 실행되는지 가리지 않음). 폼 데이터에는 {ref:{name,version}}만 저장. */
  const refBody = (i: number, n: PipelineNodeRef) => {
    const detail = n.ref.name ? details[n.ref.name] : undefined
    const cfg = detail?.versions.find((v) => v.version === n.ref.version)?.config
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))', gap: 10 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>등록 노드</span>
            <Select
              showSearch
              value={n.ref.name || undefined}
              status={!n.ref.name.trim() ? 'error' : undefined}
              placeholder={
                templates === null ? '불러오는 중…' : templates.length ? '노드 라이브러리에서 선택' : '등록된 노드 없음 — 노드 라이브러리에서 먼저 등록하세요'
              }
              options={(templates ?? []).map((t) => ({
                label: `${t.name} (최신 v${t.latestVersion})`,
                value: t.name,
              }))}
              onChange={(name) => {
                // 선택 시 기본=최신 버전(스펙 316) — 이후 버전 Select로 명시 변경 가능.
                const latest = (templates ?? []).find((t) => t.name === name)?.latestVersion ?? 1
                replaceNode(i, { ref: { name, version: latest } })
                loadDetail(name)
              }}
              style={{ width: '100%' }}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>버전</span>
            <Select
              value={n.ref.version >= 1 ? n.ref.version : undefined}
              disabled={!n.ref.name}
              placeholder="버전 선택"
              options={(detail?.versions ?? []).map((v) => ({ label: `v${v.version}`, value: v.version }))}
              onChange={(v) => replaceNode(i, { ref: { name: n.ref.name, version: v } })}
              style={{ width: '100%' }}
            />
          </div>
        </div>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          참조는 선택한 버전에 고정됩니다 — 새 버전이 발행돼도 이 노드는 바뀌지 않으며, 여기서 버전을 올릴 때만 반영됩니다.
        </span>
        {cfg ? (
          <div
            style={{
              border: '1px solid var(--color-border-secondary)',
              borderRadius: 8,
              padding: '8px 12px',
              background: 'var(--gray-2)',
            }}
          >
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 6 }}>
              실행될 설정 (읽기 전용)
            </div>
            <NodeConfigSummary config={cfg} />
          </div>
        ) : n.ref.name ? (
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>설정을 불러오는 중…</span>
        ) : null}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {/* 동작 설명은 저작(편집) 화면에만 — 오버라이드(구조 잠금)에서는 이미 아는 내용의 반복이라 생략(스펙 287 후속). */}
      {!fixedStructure && (
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginBottom: 12 }}>
          노드를 위에서 아래로 순서대로 이어 실행합니다. 노드마다 직접 설정하거나, 노드 라이브러리의 등록
          노드를 버전 고정으로 참조할 수 있습니다. 앞 노드의 결과가 다음 노드로 전달됩니다.
        </span>
      )}
      {nodes.length === 0 && (
        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)', marginBottom: 12 }}>
          {fixedStructure
            ? '노드가 없습니다 — 에이전트 편집에서 노드를 먼저 만드세요.'
            : '아직 노드가 없습니다 — 아래 "노드 추가"로 첫 단계를 만드세요(최소 1개 필요).'}
        </span>
      )}
      {nodes.map((n, i) => (
        <div key={i} style={{ display: 'flex', flexDirection: 'column' }}>
          {i > 0 && (
            <div style={{ textAlign: 'center', color: 'var(--color-text-quaternary)', fontSize: 14, lineHeight: '18px' }}>
              ↓
            </div>
          )}
          {/* 접이식 카드(스펙 275) — collapsible="icon": 아이콘만 토글해 헤더의 이름 Input·버튼
              클릭이 접힘을 오토글하지 않게(스펙 123 함정). 접힘 헤더=이름+요약 한 줄(+미완성 표시). */}
          <Collapse
            size="small"
            collapsible="icon"
            activeKey={open.includes(i) ? ['n'] : []}
            onChange={(keys) =>
              setOpen((o) => (keys.length ? [...new Set([...o, i])] : o.filter((k) => k !== i)))
            }
            style={{ marginTop: i > 0 ? 4 : 0 }}
            items={[
              {
                key: 'n',
                label: (
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', minWidth: 0 }}>
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
                    {isNodeRef(n) ? (
                      // 참조 노드(스펙 316) — 이름은 라이브러리가 소유(name@version), 항상 읽기 전용 표기.
                      <>
                        <span style={{ flex: 'none', fontSize: 13, fontWeight: 500 }}>{refLabel(n)}</span>
                        <Tag color="geekblue" style={{ flex: 'none', margin: 0 }}>
                          라이브러리
                        </Tag>
                        {!open.includes(i) && nodeInvalid(n) && (
                          <Tag color="red" style={{ flex: 'none', margin: 0 }}>
                            작성 필요
                          </Tag>
                        )}
                      </>
                    ) : open.includes(i) && !fixedStructure ? (
                      <Input
                        placeholder={`노드 ${i + 1} 이름 (선택 — 예: 분석)`}
                        value={n.name}
                        onChange={(e) => setNode(i, { name: e.target.value })}
                        style={{ flex: 1 }}
                      />
                    ) : open.includes(i) ? (
                      // 구조 불변 모드(스펙 287): 이름=구조 식별자라 읽기 전용(서버가 저장본 유지).
                      <span style={{ flex: 'none', fontSize: 13, fontWeight: 500 }}>
                        {n.name?.trim() || `노드 ${i + 1}`}
                      </span>
                    ) : (
                      <>
                        <span style={{ flex: 'none', fontSize: 13, fontWeight: 500 }}>
                          {n.name?.trim() || `노드 ${i + 1}`}
                        </span>
                        {nodeInvalid(n) && (
                          <Tag color="red" style={{ flex: 'none', margin: 0 }}>
                            작성 필요
                          </Tag>
                        )}
                        <span
                          style={{
                            fontSize: 12,
                            color: 'var(--color-text-tertiary)',
                            minWidth: 0,
                            overflow: 'hidden',
                            whiteSpace: 'nowrap',
                            textOverflow: 'ellipsis',
                          }}
                        >
                          {n.prompt.trim().slice(0, 60)}
                        </span>
                      </>
                    )}
                  </div>
                ),
                extra: fixedStructure ? undefined : (
                  <div style={{ display: 'flex', gap: 0, alignItems: 'center' }}>
                    <Button size="small" type="text" disabled={i === 0} onClick={() => move(i, -1)} title="위로">
                      ↑
                    </Button>
                    <Button size="small" type="text" disabled={i === nodes.length - 1} onClick={() => move(i, 1)} title="아래로">
                      ↓
                    </Button>
                    <Button size="small" danger type="text" onClick={() => remove(i)}>
                      삭제
                    </Button>
                  </div>
                ),
                children: (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {/* 설정 방식 전환(스펙 316) — 같은 노드의 표현 전환이라 Segmented(스펙 212 규칙).
                        전환하면 해당 모드 데이터만 유효(단순 규칙 — 직접 설정 입력은 참조 전환 시 버려짐). */}
                    {!fixedStructure && (
                      <Segmented
                        value={isNodeRef(n) ? 'ref' : 'inline'}
                        onChange={(v) => {
                          if (v === 'ref' && !isNodeRef(n)) replaceNode(i, { ref: { name: '', version: 0 } })
                          else if (v === 'inline' && isNodeRef(n)) replaceNode(i, blankInline())
                        }}
                        options={[
                          { label: '직접 설정', value: 'inline' },
                          { label: '라이브러리 참조', value: 'ref' },
                        ]}
                      />
                    )}
                    {isNodeRef(n) ? (
                      fixedStructure ? (
                        // 방어적 분기 — 오버라이드 베이스는 해석된 인라인(resolvedNodes)이라 정상
                        // 경로에선 도달하지 않는다. 도달 시 정직하게 참조임을 표기(편집 불가).
                        <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>
                          라이브러리 참조 노드 — {refLabel(n)} (여기서 편집할 수 없습니다)
                        </span>
                      ) : (
                        refBody(i, n)
                      )
                    ) : (
                      <NodeConfigFields
                        value={n}
                        onChange={(patch) => setNode(i, patch)}
                        models={models}
                        personas={personas}
                        mcpServers={mcpServers}
                        docOptions={docOptions}
                        memoryOptions={memoryOptions}
                      />
                    )}
                  </div>
                ),
              },
            ]}
          />
        </div>
      ))}
      {!fixedStructure && (
        <Button onClick={add} style={{ alignSelf: 'flex-start', marginTop: nodes.length ? 12 : 0 }}>
          + 노드 추가
        </Button>
      )}
    </div>
  )
}

/* 저장 가능한 최소 조건(스펙 259) — 노드 ≥1, 각 노드 프롬프트+모델 채움. 참조 노드(스펙 316)는
   name+version 선택이 완성 조건(프롬프트·모델은 등록 config가 보유 — 서버 검증 통과분이라 재검사 없음).
   폼 스텝/저장 게이트가 소비. */
export function pipelineValid(nodes: (PipelineNode | PipelineNodeRef)[] | undefined): boolean {
  return (
    !!nodes?.length &&
    nodes.every((n) =>
      isNodeRef(n) ? n.ref.name.trim() !== '' && n.ref.version >= 1 : n.prompt.trim() !== '' && n.model.trim() !== '',
    )
  )
}
