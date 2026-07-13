/* 노드 라이브러리(스펙 316) — 노드형 파이프라인의 재사용 노드를 1급 자산으로 등록·관리.
   등록 노드는 (name, version) 단위 **불변** — 수정=새 버전 발행(update 없음, 구조로 강제).
   에이전트 nodes[]가 {ref:{name,version}}으로 버전 핀 고정 참조하며, 참조 중인 버전은 삭제 불가(409).
   목록(이름별 그룹) → 행 클릭 드로어(버전 히스토리·usedBy·삭제) → 등록/새 버전 발행 모달.
   노드 편집 필드는 NodeListEditor에서 추출한 NodeConfigFields 재사용(폼 필드·라벨·순서 단일 출처). */
import { useEffect, useState } from 'react'
import { Tag, Button, Input, Tooltip, Alert, Modal, Popconfirm, message } from 'antd'
import { Page, DataTable, Drawer, type Column } from '../shared'
import { validateName, NAME_HINT } from '../naming'
import { fmtTime } from '../format'
import { Icon } from '../icons'
import { type BlockCategory, type PipelineNode } from '../mockData'
import {
  getBlocks,
  listModels,
  listCollections,
  listNodeTemplates,
  getNodeTemplate,
  createNodeTemplate,
  deleteNodeTemplateVersion,
  type NodeTemplateGroup,
  type NodeTemplateDetail,
  type Model,
  type Collection,
} from '../../api'
import { useAsyncData, runWithToast } from '../../hooks'
import { NodeConfigFields, NodeConfigSummary } from './agents/NodeListEditor'
import { chatModelOptions } from './agents/ModelFields'
import { safeToolName } from './agents/AgentForm'

/* 등록(create) / 기존 버전 config 프리필로 새 버전 발행(republish). 둘 다 POST 하나 —
   서버가 이름 존재 여부로 v1/다음 버전을 정한다(스펙 316). */
type TplFormState =
  | { mode: 'create' }
  | { mode: 'republish'; name: string; description: string; config: PipelineNode }

function NodeTemplateForm({
  form,
  models,
  personas,
  mcpServers,
  docOptions,
  memoryOptions,
  onCancel,
  onSaved,
}: {
  form: TplFormState | null
  models: Model[]
  personas: { name: string; body: string }[]
  mcpServers: { name: string; tools?: string[] }[]
  docOptions: { label: string; value: string }[]
  memoryOptions: { label: string; value: string }[]
  onCancel: () => void
  onSaved: () => void
}) {
  const blank = (): PipelineNode => ({
    name: '',
    prompt: '',
    model: chatModelOptions(models)[0]?.value ?? '',
    tools: [],
    context: 'carry',
  })
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [config, setConfig] = useState<PipelineNode>(blank)
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (!form) return
    if (form.mode === 'republish') {
      setName(form.name)
      setDescription(form.description)
      // 깊은 복사 — 프리필 편집이 드로어에 보이는 원본 config를 오염시키지 않게.
      setConfig(structuredClone(form.config))
    } else {
      setName('')
      setDescription('')
      setConfig(blank())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form])
  if (!form) return null
  const isRepub = form.mode === 'republish'

  const submit = async () => {
    const nameErr = validateName(name.trim()) // 식별 이름 규칙(스펙 148 — 에이전트 name 규칙 준용)
    if (nameErr) {
      message.warning(nameErr)
      return
    }
    // 저장 최소 조건은 노드형 노드와 동일(스펙 259/316) — 프롬프트·모델 필수. 상한·상세 검증은
    // 서버(_normalize_node 동일 화이트리스트)가 진실원(422 detail 한국어 → 토스트 표면화).
    if (!config.prompt.trim()) {
      message.warning('프롬프트를 입력하세요')
      return
    }
    if (!config.model.trim()) {
      message.warning('모델을 선택하세요')
      return
    }
    setSaving(true)
    const ok = await runWithToast(
      () => createNodeTemplate({ name: name.trim(), description: description.trim() || null, config }),
      {
        success: isRepub ? '새 버전이 발행되었습니다' : '노드가 등록되었습니다',
        errorPrefix: isRepub ? '발행 실패' : '등록 실패',
      },
    )
    setSaving(false)
    if (ok) onSaved()
  }

  const nameErr = name.trim() ? validateName(name.trim()) : null
  return (
    <Modal
      open={!!form}
      width={640}
      title={isRepub ? `새 버전 발행 · ${form.name}` : '새 노드 등록'}
      okText={isRepub ? '새 버전 발행' : '등록'}
      cancelText="취소"
      onCancel={onCancel}
      onOk={() => void submit()}
      okButtonProps={{ loading: saving }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '64vh', overflow: 'auto' }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 0 }}
          title={
            isRepub
              ? '발행된 버전은 바뀌지 않습니다 — 이 내용은 다음 버전으로 새로 발행되며, 기존 버전을 참조하는 에이전트는 그대로 유지됩니다.'
              : '등록한 노드는 노드형 에이전트에서 버전을 핀 고정해 참조할 수 있습니다. 같은 이름으로 다시 등록하면 다음 버전이 발행됩니다.'
          }
        />
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>식별 이름</span>
          <Input
            placeholder="예: summarize-step"
            value={name}
            disabled={isRepub} // 새 버전 발행은 같은 이름에 쌓인다 — 이름 변경=별개 노드 등록
            status={nameErr ? 'error' : undefined}
            onChange={(e) => setName(e.target.value)}
          />
          <span style={{ fontSize: 12, color: nameErr ? 'var(--red-6)' : 'var(--color-text-tertiary)' }}>
            {nameErr ?? (isRepub ? '이름은 버전 계보의 식별자라 바꿀 수 없습니다.' : NAME_HINT)}
          </span>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>
            설명 <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(선택 — 부가 정보)</span>
          </span>
          <Input placeholder="예: 입력을 3줄로 요약하는 단계" value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        {/* 노드 설정 — NodeListEditor 카드 본문과 같은 공용 필드(NodeConfigFields, 스펙 316 단일 출처):
            프롬프트 → 모델 → 기억(단기·장기) → 도구·문서 → 받기·형식. */}
        <NodeConfigFields
          value={config}
          onChange={(patch) => setConfig((c) => ({ ...c, ...patch }))}
          models={models}
          personas={personas}
          mcpServers={mcpServers}
          docOptions={docOptions}
          memoryOptions={memoryOptions}
        />
      </div>
    </Modal>
  )
}

export default function NodeLibraryView() {
  const { data: groups, reload } = useAsyncData<NodeTemplateGroup[]>(listNodeTemplates, [], {
    errorMsg: '노드 목록을 불러오지 못했습니다',
  })
  // 노드 편집 폼 카탈로그 — AgentForm이 NodeListEditor에 주는 것과 같은 소스(blocks/models/collections).
  const { data: blocks } = useAsyncData<Record<string, BlockCategory>>(getBlocks, [], {
    errorMsg: '블록을 불러오지 못했습니다',
  })
  const { data: models } = useAsyncData<Model[]>(() => listModels(), [], {
    errorMsg: '모델 목록을 불러오지 못했습니다',
  })
  const { data: collections } = useAsyncData<Collection[]>(listCollections, [], {
    errorMsg: '컬렉션 목록을 불러오지 못했습니다',
  })
  const [detailName, setDetailName] = useState<string | null>(null)
  const { data: detail, reload: reloadDetail } = useAsyncData<NodeTemplateDetail | null>(
    () => (detailName ? getNodeTemplate(detailName) : Promise.resolve(null)),
    [detailName],
    { errorMsg: '노드 상세를 불러오지 못했습니다' },
  )
  const [form, setForm] = useState<TplFormState | null>(null)

  const personas = (blocks?.persona?.items ?? []).map((p) => ({ name: p.name, body: p.body ?? '' }))
  const mcpServers = blocks?.mcp?.items ?? []
  // 노드 회상 선택지 — 장기 기억(mem0). AgentForm nodeMemoryOptions와 동일 규칙.
  const memoryOptions = (blocks?.memory?.items ?? [])
    .map((m) => ({ label: m.name, value: m.name }))
  // 문서 검색은 컬렉션별 도구(스펙 268 P1) — 런타임명 search_documents__<컬렉션>.
  const docOptions = (collections ?? []).map((c) => ({ label: c.name, value: safeToolName('search_documents', c.name) }))

  const doDelete = async (version: number) => {
    if (!detailName) return
    const lastOne = (detail?.versions ?? []).length === 1
    // 409(참조 중)의 detail(에이전트 이름 목록)은 httpError→runWithToast가 그대로 표면화.
    const ok = await runWithToast(() => deleteNodeTemplateVersion(detailName, version), {
      success: `${detailName} v${version} 버전이 삭제되었습니다`,
      errorPrefix: '삭제 실패',
    })
    if (ok) {
      reload()
      // 마지막 버전 삭제=노드 자체가 사라짐 — 상세 재조회는 404라 드로어를 닫는다.
      if (lastOne) setDetailName(null)
      else reloadDetail()
    }
  }

  const columns: Column<NodeTemplateGroup>[] = [
    {
      key: 'name',
      title: '이름',
      render: (r) => (
        <code style={{ fontFamily: 'var(--font-family-code)', color: 'var(--cyan-7)', fontSize: 13 }}>{r.name}</code>
      ),
    },
    {
      key: 'kind',
      title: '종류',
      width: 80,
      // 종류(스펙 317): 설정=폼 저작 / 코드=신뢰 레지스트리에서 부팅 시 자동 발행(코드 배포로만 변경).
      render: (r) =>
        r.kind === 'code' ? <Tag color="purple">코드</Tag> : <Tag>설정</Tag>,
    },
    {
      key: 'latestVersion',
      title: '최신 버전',
      width: 100,
      render: (r) => <Tag color="geekblue">v{r.latestVersion}</Tag>,
    },
    {
      key: 'versionCount',
      title: '버전 수',
      width: 90,
      align: 'right',
      render: (r) => <span style={{ color: 'var(--color-text-secondary)' }}>{r.versionCount}</span>,
    },
    {
      key: 'usedByCount',
      title: '사용 에이전트',
      width: 110,
      align: 'right',
      render: (r) => <span style={{ color: 'var(--color-text-secondary)' }}>{r.usedByCount}개</span>,
    },
    {
      key: 'description',
      title: '설명',
      render: (r) => (
        <span style={{ color: 'var(--color-text-tertiary)', fontSize: 13 }}>{r.description || '—'}</span>
      ),
    },
  ]

  return (
    <Page
      title="노드"
      subtitle="미리 정의해 두는 등록 노드 — 노드형 에이전트가 버전을 핀 고정해 참조"
      actions={
        <Button type="primary" icon={<Icon name="plus" />} onClick={() => setForm({ mode: 'create' })}>
          새 노드
        </Button>
      }
    >
      <DataTable columns={columns} rows={groups ?? []} rowKey="name" onRowClick={(r) => setDetailName(r.name)} empty="등록된 노드 없음 — “새 노드”로 첫 노드를 등록하세요" />

      <Drawer
        open={!!detailName}
        title={detailName ?? ''}
        width={520}
        onClose={() => setDetailName(null)}
      >
        {detailName ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              {/* 코드 노드(스펙 317)는 발행·삭제가 코드 배포 소관 — 안내를 종류에 맞춘다. */}
              {detail?.versions[0]?.kind === 'code'
                ? '코드로 작성된 노드입니다 — 버전 발행·삭제는 코드 배포로 이뤄지며, 에이전트는 버전을 핀 고정해 참조합니다.'
                : '발행된 버전은 바뀌지 않습니다 — 수정하려면 원하는 버전으로 새 버전을 발행하세요. 참조 중인 버전은 삭제할 수 없습니다.'}
            </span>
            {(detail?.versions ?? []).map((v) => (
              <div
                key={v.id}
                style={{
                  border: '1px solid var(--color-border-secondary)',
                  borderRadius: 'var(--radius-lg)',
                  padding: '10px 12px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <Tag color="geekblue" style={{ margin: 0 }}>
                    v{v.version}
                  </Tag>
                  {v.kind === 'code' && (
                    <Tag color="purple" style={{ margin: 0 }}>
                      코드
                    </Tag>
                  )}
                  <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                    {fmtTime(v.created_at ?? '') || '—'}
                  </span>
                  <span style={{ flex: 1 }} />
                  {v.kind === 'code' ? (
                    /* 코드 노드(스펙 317) — 발행·삭제는 코드 배포로만(API는 409). 버튼 대신 안내. */
                    <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                      코드로 관리됩니다 — 발행·삭제는 코드 배포로 이뤄집니다
                    </span>
                  ) : (
                    <>
                      <Button
                        size="small"
                        onClick={() =>
                          setForm({
                            mode: 'republish',
                            name: detailName,
                            description: v.description ?? '',
                            config: v.config,
                          })
                        }
                      >
                        이 버전으로 새 버전 발행
                      </Button>
                      {v.usedBy.length > 0 || v.usedByHidden > 0 ? (
                        <Tooltip title="참조 중인 에이전트가 있어 삭제할 수 없습니다">
                          <Button size="small" danger disabled>
                            삭제
                          </Button>
                        </Tooltip>
                      ) : (
                        <Popconfirm
                          title={`v${v.version} 버전을 삭제할까요?`}
                          description="삭제하면 되돌릴 수 없습니다."
                          okText="삭제"
                          cancelText="취소"
                          okButtonProps={{ danger: true }}
                          onConfirm={() => void doDelete(v.version)}
                        >
                          <Button size="small" danger>
                            삭제
                          </Button>
                        </Popconfirm>
                      )}
                    </>
                  )}
                </div>
                {v.description ? <span style={{ fontSize: 13 }}>{v.description}</span> : null}
                {/* config 요약 — 참조 미리보기와 같은 렌더러(NodeConfigSummary, 단일 출처). */}
                <NodeConfigSummary config={v.config} />
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>사용 에이전트:</span>
                  {v.usedBy.map((a) => (
                    <Tag key={a} color="blue" style={{ margin: 0 }}>
                      {a}
                    </Tag>
                  ))}
                  {/* 가시 범위 밖 참조(스펙 317) — 이름은 못 보여줘도 수는 정직하게(삭제 disabled의 근거). */}
                  {v.usedByHidden > 0 && (
                    <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                      {/* 보이는 태그가 없으면 "외"가 어색 — 수만 표기. */}
                      {v.usedBy.length ? `외 ${v.usedByHidden}개(비공개)` : `${v.usedByHidden}개(비공개)`}
                    </span>
                  )}
                  {v.usedBy.length === 0 && v.usedByHidden === 0 && (
                    <span style={{ fontSize: 12, color: 'var(--color-text-quaternary)' }}>없음</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </Drawer>

      <NodeTemplateForm
        form={form}
        models={models ?? []}
        personas={personas}
        mcpServers={mcpServers}
        docOptions={docOptions}
        memoryOptions={memoryOptions}
        onCancel={() => setForm(null)}
        onSaved={() => {
          setForm(null)
          reload()
          if (detailName) reloadDetail()
        }}
      />
    </Page>
  )
}
