/* my-agents admin — RAG 컬렉션 + 문서 인제스트 + retrieval 시험 뷰 (스펙 036 + 072).
   컬렉션(임베딩 모델 고정 + 청크 정책) 생성 → 문서 업로드(인제스트 write path) →
   상태/건강 점검 → **검색 시험**(스펙 072: 인-챗 도구와 같은 코어를 타는 retrieval을
   에이전트 채팅 없이 즉석 확인). 목록/페이지 셸은 shared의 Page/DataTable, 상호작용은 antd 6. */
import { useState, useEffect } from 'react'
import {
  Alert,
  Tag,
  Button,
  Modal,
  Drawer,
  Input,
  InputNumber,
  Select,
  Tabs,
  Table,
  Tooltip,
  Upload,
  Popconfirm,
  message,
} from 'antd'
import type { UploadProps, TableProps } from 'antd'
import { Page, DataTable, type Column } from '../shared'
import { validateName, NAME_HINT } from '../naming'
import { PagedListShell, type ListController } from './PagedListShell'
import { Icon } from '../icons'
import { RetrievalTestDrawer } from './RetrievalTestDrawer'
import { DocumentEditorModal } from './DocumentEditorModal'
import {
  listCollections,
  createCollection,
  updateCollection,
  deleteCollection,
  collectionHealth,
  listDocuments,
  uploadDocument,
  deleteDocument,
  listModels,
  searchCollection,
  reindexCollection,
  listReindexEvents,
  type Collection,
  type RagDocument,
  type CollectionHealth,
  type SearchHit,
  type Model,
  type ReindexEvent,
} from '../../api'
import { useAsyncData, runWithToast } from '../../hooks'

const { TextArea } = Input

const codeStyle = { fontFamily: 'var(--font-family-code)', fontSize: 13 }

/* 바이트 → 사람이 읽는 크기. */
function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

/* 컬렉션 상태 → Tag 색. empty=default, ingesting=processing(파랑), ready=success(초록), error=error(빨강). */
function collectionStatusTag(status: string) {
  switch (status) {
    case 'ready':
      return <Tag color="success">준비됨</Tag>
    case 'ingesting':
      return <Tag color="processing">인제스트 중</Tag>
    case 'reindexing':
      return <Tag color="processing">재인덱싱 중</Tag>
    case 'error':
      return <Tag color="error">오류</Tag>
    case 'empty':
    default:
      return <Tag>비어 있음</Tag>
  }
}

/* 문서 상태 → Tag 색. parsing/embedding=처리 중, ready=완료, error=오류. */
function docStatusTag(status: string) {
  switch (status) {
    case 'ready':
      return <Tag color="success">완료</Tag>
    case 'parsing':
      return <Tag color="processing">파싱 중</Tag>
    case 'embedding':
      return <Tag color="processing">임베딩 중</Tag>
    case 'error':
      return <Tag color="error">오류</Tag>
    default:
      return <Tag>{status}</Tag>
  }
}

/* ---- 컬렉션 생성 모달 ---- */
interface CreateFormData {
  name: string // 식별 이름(규칙, 스펙 148)
  kind: 'document' | 'entity' // 종류 축(스펙 149)
  schemaText: string // 엔티티 행 검증 JSON Schema 원문(선택, 스펙 149) — 제출 시 파싱
  description: string
  embedding_model_id: string
  chunk_size: number
  chunk_overlap: number
}

const blankCreate: CreateFormData = {
  name: '',
  kind: 'document',
  schemaText: '',
  description: '',
  embedding_model_id: '',
  chunk_size: 1000,
  chunk_overlap: 200,
}

function CreateModal({
  open,
  models,
  initialKind,
  onCancel,
  onSubmit,
}: {
  open: boolean
  models: Model[]
  initialKind: 'document' | 'entity' // 스펙 212: 열려 있던 탭의 종류를 기본 선택(모달 안에서 변경은 계속 가능)
  onCancel: () => void
  onSubmit: (data: CreateFormData) => void
}) {
  const [f, setF] = useState<CreateFormData>(blankCreate)

  // mock 필터(스펙 218, 사용자 지시): 실제(비-mock) 임베딩 모델이 하나라도 있으면 mock 모델은
  // 선택지에서 제외한다. mock만 있으면(개발 초기) 그대로 노출해 컬렉션 생성이 막히지 않게 한다.
  const hasReal = models.some((m) => m.provider_kind !== 'mock')
  const selectable = hasReal ? models.filter((m) => m.provider_kind !== 'mock') : models

  useEffect(() => {
    if (open) {
      // 기본 임베딩 모델을 프리셀렉트(is_default) — 없으면 모델이 하나일 때만 그걸로(스펙 175).
      // 임베딩은 생성 후 불변이라, 흔한 선택을 미리 채워 실수 여지를 줄인다. selectable에서만 고른다.
      const def = selectable.find((m) => m.is_default) ?? (selectable.length === 1 ? selectable[0] : undefined)
      setF({ ...blankCreate, kind: initialKind, embedding_model_id: def?.id ?? '' })
    }
    // selectable은 models 파생 — models 변경 시 재계산
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, models, initialKind])

  const set = <K extends keyof CreateFormData>(k: K, v: CreateFormData[K]) =>
    setF((s) => ({ ...s, [k]: v }))

  return (
    <Modal
      open={open}
      width={520}
      title="컬렉션 생성"
      okText="생성"
      cancelText="취소"
      onCancel={onCancel}
      onOk={() => onSubmit(f)}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxHeight: '60vh', overflow: 'auto' }}>
        {/* 불변 결정 3인방(이름·종류·임베딩)을 상위에 — 생성 후 못 바꾸니 먼저 정한다(스펙 175). */}
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>식별 이름</span>
          <Input
            placeholder="예: docs-kb"
            value={f.name}
            status={f.name.trim() && validateName(f.name.trim()) ? 'error' : undefined}
            onChange={(e) => set('name', e.target.value)}
          />
          <span style={{ fontSize: 12, color: f.name.trim() && validateName(f.name.trim()) ? 'var(--red-6)' : 'var(--color-text-tertiary)' }}>
            {(f.name.trim() && validateName(f.name.trim())) || NAME_HINT}
          </span>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>종류</span>
          <Select
            value={f.kind}
            onChange={(v) => set('kind', v)}
            style={{ width: '100%' }}
            options={[
              { label: '문서형 — 파일을 잘라(청킹) 의미 검색', value: 'document' },
              { label: '엔티티형 — JSONL 한 줄=한 엔티티, metadata 동반 검색', value: 'entity' },
            ]}
          />
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            {f.kind === 'entity'
              ? 'JSONL 형식: {"metadata": {…id들}, "data": {…임베딩 소스}} — data를 임베딩하고 검색 결과에 metadata가 함께 나옵니다. 생성 후 종류는 변경할 수 없습니다.'
              : 'PDF·텍스트·마크다운을 올려 청킹·임베딩합니다. 생성 후 종류는 변경할 수 없습니다.'}
          </span>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>
            임베딩 모델 <span style={{ color: 'var(--red-6)', fontWeight: 400 }}>(생성 후 변경 불가)</span>
          </span>
          <Select
            value={f.embedding_model_id || undefined}
            onChange={(v) => set('embedding_model_id', v)}
            style={{ width: '100%' }}
            popupMatchSelectWidth={false}
            placeholder={selectable.length ? '임베딩 모델 선택' : '먼저 임베딩 모델을 등록하세요'}
            options={selectable.map((m) => ({
              // 이름과 model_id가 같으면(HF 경로 등) 중복 표기 생략 — 라벨 과다 길이 방지(스펙 218).
              label: `${m.name}${m.model_id && m.model_id !== m.name ? ` — ${m.model_id}` : ''}${m.is_default ? ' · 기본' : ''}`,
              value: m.id,
            }))}
          />
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            문서를 벡터로 바꾸는 모델입니다. 차원이 고정되므로 생성 후 모델과 차원은 변경할 수 없습니다.
          </span>
        </label>
        {f.kind === 'entity' ? (
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>
              JSON Schema <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(선택 — 업로드 행 검증)</span>
            </span>
            <TextArea
              rows={5}
              placeholder={'{"type": "object", "required": ["metadata", "data"], …}'}
              value={f.schemaText}
              onChange={(e) => set('schemaText', e.target.value)}
              style={{ fontFamily: 'var(--font-family-code)', fontSize: 12 }}
            />
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              등록하면 업로드하는 모든 행을 이 스키마로 검증합니다(위반 시 행 번호와 함께 거부) — SQL 변경으로 필드가 어긋나는 것을 잡아줍니다.
            </span>
          </label>
        ) : null}
        {/* 편집 가능 항목(설명)은 아래로 — 언제든 바꿀 수 있음(스펙 210). */}
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>
            설명 <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(선택 — 부가 정보)</span>
          </span>
          <TextArea
            rows={3}
            placeholder="이 컬렉션에 담길 지식의 내용"
            value={f.description}
            onChange={(e) => set('description', e.target.value)}
          />
        </label>
        {f.kind === 'document' ? (
          <div style={{ display: 'flex', gap: 16 }}>
            {/* 카피 감사(축3) 보강: '청크' 첫 노출부에 일반인용 한 줄 설명 — 도메인어는 없애지 않고 설명 추가 */}
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
              <span style={{ fontSize: 14, fontWeight: 500 }}>
                청크 크기{' '}
                <Tooltip title="청크 = 문서를 잘게 나눈 조각. 검색은 이 조각 단위로 이뤄집니다. 크기는 조각 하나의 글자 수.">
                  <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400, cursor: 'help' }}>(?)</span>
                </Tooltip>
              </span>
              <InputNumber
                min={1}
                style={{ width: '100%' }}
                value={f.chunk_size}
                onChange={(v) => set('chunk_size', v ?? blankCreate.chunk_size)}
              />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
              <span style={{ fontSize: 14, fontWeight: 500 }}>
                청크 겹침{' '}
                <Tooltip title="이웃한 두 조각이 겹쳐서 공유하는 글자 수. 문장이 조각 경계에서 잘려 문맥이 끊기는 걸 줄입니다(보통 크기의 10~20%).">
                  <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400, cursor: 'help' }}>(?)</span>
                </Tooltip>
              </span>
              <InputNumber
                min={0}
                style={{ width: '100%' }}
                value={f.chunk_overlap}
                onChange={(v) => set('chunk_overlap', v ?? blankCreate.chunk_overlap)}
              />
            </label>
          </div>
        ) : null}
      </div>
    </Modal>
  )
}

/* ---- 컬렉션 편집 모달(별명·설명·청크) — 행의 편집 버튼에서 열림(스펙 176). ----
   식별이름·모델·차원은 불변이라 노출하지 않는다. 편집 진입은 소유자만(행 버튼 can_manage 게이트)이고
   백엔드도 assert_may_manage로 이중 방어. */
function EditModal({
  collection,
  onCancel,
  onSaved,
}: {
  collection: Collection | null
  onCancel: () => void
  onSaved: () => void
}) {
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (collection) {
      setDescription(collection.description ?? '')
    }
    /* eslint-disable-next-line */
  }, [collection?.id])

  const isEntity = collection?.kind === 'entity'

  const save = async () => {
    if (!collection) return
    setSaving(true)
    const ok = await runWithToast(() =>
      updateCollection(collection.id, {
        description,
        // 스펙 198: 청크 크기·겹침은 생성 후 불변 → 수정에서 제거.
      }),
      { success: '컬렉션을 수정했습니다' },
    )
    setSaving(false)
    if (ok) {
      onSaved()
      onCancel()
    }
  }

  return (
    <Modal
      open={!!collection}
      width={480}
      title={collection ? `컬렉션 편집 · ${collection.name}` : ''}
      okText="저장"
      cancelText="취소"
      confirmLoading={saving}
      onCancel={onCancel}
      onOk={() => void save()}
    >
      {collection ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>
              설명 <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(선택 — 부가 정보)</span>
            </span>
            <TextArea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          {/* 스펙 312: 청크 정책·모델은 재인덱싱(행의 ↻)으로 변경 가능해졌다 — 원본을 저장하므로.
             여기선 현재 값을 참고 표시하고, 변경 경로를 재인덱싱으로 안내(카피 감사 축3). */}
          {!isEntity ? (
            <span style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
              청크(문서를 잘게 나눈 조각) 정책: 크기 <b>{collection.chunk_size}</b> · 겹침 <b>{collection.chunk_overlap}</b>
            </span>
          ) : null}
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            {isEntity
              ? '엔티티 컬렉션은 청크 정책이 없습니다. 임베딩 모델은 재인덱싱(행의 ↻ 버튼)으로 바꿀 수 있습니다 — 식별 이름·차원은 고정입니다.'
              : '임베딩 모델·청크 크기·겹침은 재인덱싱(행의 ↻ 버튼)으로 바꿀 수 있습니다 — 저장된 원본에서 다시 임베딩합니다. 식별 이름·차원은 고정입니다.'}
          </span>
        </div>
      ) : null}
    </Modal>
  )
}

/* ---- 문서 관리 드로어 ---- */
/* 재인덱싱 모달(스펙 312 도입, 313 무중단) — 임베딩 모델 교체(같은 차원)와/또는 청크 크기·겹침 재청킹.
   저장된 원본에서 다시 임베딩. 재인덱싱 중에도 검색은 무중단(MVCC 원자 스왑 — 진행 중엔 이전 결과,
   완료 순간 새 결과)·업로드/편집만 잠깐 대기·평가 이력 보존.
   같은 차원(1024) 강제는 서버가 판정(모델에 차원 미저장 → 사전 필터 불가, 현재 모든 임베딩=1024). */
function ReindexModal({
  collection,
  models,
  onCancel,
  onDone,
}: {
  collection: Collection | null
  models: Model[]
  onCancel: () => void
  onDone: () => void
}) {
  const isEntity = collection?.kind === 'entity'
  const [modelId, setModelId] = useState('')
  const [size, setSize] = useState(1000)
  const [overlap, setOverlap] = useState(200)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    if (collection) {
      setModelId(collection.embedding_model_id)
      setSize(collection.chunk_size)
      setOverlap(collection.chunk_overlap)
    }
    /* eslint-disable-next-line */
  }, [collection?.id])

  // 재인덱싱 이력 — 모달이 이 컬렉션으로 열릴 때 로드(모델·청크 계보).
  const { data: events, reload: reloadEvents } = useAsyncData<ReindexEvent[]>(
    () => (collection ? listReindexEvents(collection.id) : Promise.resolve([])),
    [collection?.id],
  )

  const modelChanged = !!collection && modelId !== collection.embedding_model_id
  const chunkChanged =
    !isEntity &&
    !!collection &&
    (size !== collection.chunk_size || overlap !== collection.chunk_overlap)
  const canRun = modelChanged || chunkChanged

  const run = async () => {
    if (!collection || !canRun) return
    const body: { embedding_model_id?: string; chunk_size?: number; chunk_overlap?: number } = {}
    if (modelChanged) body.embedding_model_id = modelId
    if (chunkChanged) {
      body.chunk_size = size
      body.chunk_overlap = overlap
    }
    setRunning(true)
    // 서버가 완료까지 동기 처리(쓰기잠금→재임베딩→원자 스왑→해제, 검색은 무중단). 차원 불일치·원본
    // 없는 문서는 4xx로 사유 노출.
    const ok = await runWithToast(() => reindexCollection(collection.id, body), {
      success: '재인덱싱을 마쳤습니다',
      errorPrefix: '재인덱싱 실패',
    })
    setRunning(false)
    if (ok) {
      reloadEvents()
      onDone()
      onCancel()
    }
  }

  const chunkStr = (s: number | null, o: number | null) => (s == null ? '—' : `${s}/${o}`)
  const eventCols: TableProps<ReindexEvent>['columns'] = [
    {
      title: '모델',
      key: 'model',
      render: (_, e) =>
        e.from_model_name === e.to_model_name
          ? (e.to_model_name ?? '—')
          : `${e.from_model_name ?? '—'} → ${e.to_model_name ?? '—'}`,
    },
    {
      title: '청크(크기/겹침)',
      key: 'chunk',
      render: (_, e) =>
        e.from_chunk_size === e.to_chunk_size && e.from_chunk_overlap === e.to_chunk_overlap
          ? chunkStr(e.to_chunk_size, e.to_chunk_overlap)
          : `${chunkStr(e.from_chunk_size, e.from_chunk_overlap)} → ${chunkStr(e.to_chunk_size, e.to_chunk_overlap)}`,
    },
    { title: '청크 수', dataIndex: 'chunk_count', key: 'count', width: 70, align: 'right' },
    {
      title: '상태',
      key: 'status',
      width: 70,
      render: (_, e) =>
        e.status === 'ok' ? (
          <Tag color="success">완료</Tag>
        ) : (
          <Tooltip title={e.error ?? ''}>
            <Tag color="error">실패</Tag>
          </Tooltip>
        ),
    },
  ]

  return (
    <Modal
      open={!!collection}
      width={580}
      title={collection ? `재인덱싱 · ${collection.name}` : ''}
      okText="재인덱싱 실행"
      cancelText="닫기"
      confirmLoading={running}
      okButtonProps={{ disabled: !canRun }}
      onCancel={onCancel}
      onOk={() => void run()}
    >
      {collection ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Alert
            type="info"
            showIcon
            title="새 설정으로 벡터를 다시 만듭니다"
            description="저장된 원본에서 다시 임베딩합니다. 재인덱싱 중에도 검색은 무중단으로 이어집니다(진행 중엔 이전 결과, 완료 순간 새 결과). 업로드·편집만 잠깐 대기하며, 기존 평가 이력은 그대로 보존됩니다."
          />
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>임베딩 모델</span>
            <Select
              value={modelId}
              options={models.map((m) => ({ value: m.id, label: m.name }))}
              onChange={setModelId}
            />
          </label>
          {!isEntity ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ display: 'flex', gap: 12 }}>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
                  <span style={{ fontSize: 14, fontWeight: 500 }}>청크 크기</span>
                  <InputNumber
                    style={{ width: '100%' }}
                    min={1}
                    value={size}
                    onChange={(v) => setSize(v ?? collection.chunk_size)}
                  />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
                  <span style={{ fontSize: 14, fontWeight: 500 }}>청크 겹침</span>
                  <InputNumber
                    style={{ width: '100%' }}
                    min={0}
                    value={overlap}
                    onChange={(v) => setOverlap(v ?? collection.chunk_overlap)}
                  />
                </label>
              </div>
              <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
                청크 설정을 바꾸면 원본에서 다시 자릅니다 — 이 기능 도입 후 올린 문서만 재청킹됩니다.
              </span>
            </div>
          ) : (
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              엔티티 컬렉션은 1행=1청크라 청크 정책이 없습니다 — 임베딩 모델만 바꿀 수 있습니다.
            </span>
          )}
          {!canRun ? (
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              바꿀 항목을 선택하세요 — 모델이나 청크 설정 중 하나는 현재와 달라야 재인덱싱합니다.
            </span>
          ) : null}
          {events && events.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span
                style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-text-secondary)' }}
              >
                재인덱싱 이력
              </span>
              <Table
                size="small"
                rowKey="id"
                pagination={false}
                columns={eventCols}
                dataSource={events}
                scroll={{ y: 160 }}
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </Modal>
  )
}

function DocsDrawer({
  collection,
  onClose,
  onChanged,
  onEvaluate,
}: {
  collection: Collection | null
  onClose: () => void
  onChanged: () => void
  onEvaluate?: (cid: string) => void  // 스펙 197: 평가로 단축 진입
}) {
  const [uploading, setUploading] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0) // 업로드 후 문서 목록 재조회(셸 트리거)
  const [editingDoc, setEditingDoc] = useState<RagDocument | null>(null) // 문서 편집(스펙 331)
  // 설정 편집(별명·설명·청크)은 스펙 176에서 EditModal(행 편집 버튼)로 이관 — 드로어는 문서만.

  const id = collection?.id ?? null

  const doUpload = async (file: File) => {
    if (!id) return
    setUploading(true)
    try {
      const doc = await uploadDocument(id, file)
      if (doc.status === 'error') message.error(doc.error || '인제스트에 실패했습니다')
      else message.success(`${doc.filename} 인제스트 완료`)
      setRefreshKey((k) => k + 1)
      onChanged() // 컬렉션 카운트(문서·청크)도 갱신
    } catch (e) {
      message.error(e instanceof Error ? e.message : '업로드에 실패했습니다')
    } finally {
      setUploading(false)
    }
  }

  const doDeleteDoc = async (ctl: ListController, docId: string) => {
    if (!id) return
    const ok = await runWithToast(() => deleteDocument(id, docId))
    if (ok) {
      // 페이지 마지막 문서 삭제로 빈 페이지가 되면 앞 페이지로(128 셸 보정 패턴).
      if (ctl.rowCount === 1 && ctl.page > 1) ctl.setPage(ctl.page - 1)
      else await ctl.reload()
      onChanged()
    }
  }

  const isEntity = collection?.kind === 'entity'
  const uploadProps: UploadProps = {
    // 엔티티형(스펙 149)은 JSONL만 — 형식 안내는 서버 400(행 번호)이 정밀하게 한다.
    accept: isEntity ? '.jsonl,.json' : '.pdf,.txt,.md',
    multiple: true,
    showUploadList: false,
    // 직접 처리 — antd 자동 업로드를 막고 uploadDocument로 보낸다.
    beforeUpload: (file) => {
      void doUpload(file as unknown as File)
      return false
    },
  }

  const columns = (ctl: ListController): Column<RagDocument>[] => [
    {
      key: 'filename',
      title: '파일명',
      render: (d) => (
        <span style={{ fontWeight: 500, color: 'var(--color-text-heading)', wordBreak: 'break-all' }}>
          {d.filename}
        </span>
      ),
    },
    {
      key: 'byte_size',
      title: '크기',
      width: 90,
      align: 'right',
      render: (d) => <span style={{ color: 'var(--color-text-secondary)' }}>{humanBytes(d.byte_size)}</span>,
    },
    {
      key: 'chunk_count',
      title: '청크',
      width: 70,
      align: 'right',
      render: (d) => <span style={{ color: 'var(--color-text-secondary)' }}>{d.chunk_count}</span>,
    },
    {
      key: 'status',
      title: '상태',
      width: 110,
      render: (d) =>
        d.status === 'error' && d.error ? (
          <Tooltip title={d.error}>
            <span>{docStatusTag(d.status)}</span>
          </Tooltip>
        ) : (
          docStatusTag(d.status)
        ),
    },
    {
      key: 'actions',
      title: '',
      width: 92,
      align: 'right',
      render: (d) => (
        <span style={{ display: 'inline-flex', gap: 4 }}>
          {/* 문서 편집(스펙 331, 엔티티는 332) — 소유자만. PDF/원본 미보존은 비활성+사유 툴팁. */}
          {collection?.can_manage !== false && (
            <Tooltip
              title={
                d.editable
                  ? isEntity
                    ? '행(JSONL)을 편집하면 바뀐 행만 다시 임베딩됩니다'
                    : '내용을 편집하면 바뀐 부분만 다시 임베딩됩니다'
                  : 'PDF·원본 미보존 문서는 편집할 수 없습니다 — 재업로드로 교체하세요'
              }
            >
              <Button
                type="text"
                size="small"
                disabled={!d.editable}
                icon={<Icon name="edit" />}
                onClick={() => setEditingDoc(d)}
              />
            </Tooltip>
          )}
          <Popconfirm
            title="문서를 삭제할까요?"
            okText="삭제"
            cancelText="취소"
            onConfirm={() => void doDeleteDoc(ctl, d.id)}
          >
            <Button type="text" size="small" danger icon={<Icon name="delete" />} />
          </Popconfirm>
        </span>
      ),
    },
  ]

  return (
    <Drawer
      open={!!collection}
      size={640}
      title={collection ? `문서 관리 · ${collection.name}` : ''}
      onClose={onClose}
      destroyOnHidden
      /* 스펙 197: '평가하기'를 헤더 액션으로(제목 우측) — 문서 관리 콘텐츠와 위계 안 겹침.
         문서 0개면 비활성(평가할 근거가 없음, 사유 툴팁). */
      extra={onEvaluate && collection ? (
        <Tooltip title={collection.doc_count === 0 ? '문서를 먼저 업로드하면 평가할 수 있습니다' : '이 컬렉션으로 평가 문제집을 만듭니다'}>
          <Button size="small" icon={<Icon name="experiment" />} disabled={collection.doc_count === 0} onClick={() => onEvaluate(collection.id)}>
            평가하기
          </Button>
        </Tooltip>
      ) : undefined}
    >
      {collection ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* 업로드 — 소유자/특권만(스펙 114, 백엔드도 게이트) */}
          {collection.can_manage !== false && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Upload {...uploadProps}>
              <Button type="primary" icon={<Icon name="paper-clip" />} loading={uploading}>
                {isEntity ? 'JSONL 업로드' : '문서 업로드'}
              </Button>
            </Upload>
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              {isEntity
                ? '한 줄 = {"metadata": {…}, "data": {…}} 한 엔티티. 형식이 어긋난 행이 있으면 행 번호와 함께 전체가 거부됩니다.'
                : 'PDF와 UTF-8 텍스트(.txt, .md)만 지원합니다.'}
            </span>
          </div>
          )}

          {/* 문서 목록 — 공용 셸(스펙 128): 서버 페이지네이션 + 파일명 검색. 드로어 폭 고려 10건/쪽. */}
          <PagedListShell<RagDocument>
            scopeKey={collection.id}
            fetchPage={(q, l, o) => listDocuments(collection.id, q, l, o)}
            columns={columns}
            refreshKey={refreshKey}
            pageSize={10}
            searchPlaceholder="파일명 부분일치 검색"
            emptyText={(q) => (q ? '일치하는 문서가 없습니다.' : '문서 없음')}
            errorTitle="문서를 불러오지 못했습니다"
          />

          {/* 문서 편집 에디터(스펙 331, 엔티티 332) — 저장 시 그 문서만 재청킹·변경 청크만 재임베딩. */}
          <DocumentEditorModal
            collectionId={collection.id}
            entity={isEntity}
            doc={editingDoc}
            onClose={() => setEditingDoc(null)}
            onSaved={() => {
              setRefreshKey((k) => k + 1)
              onChanged() // 컬렉션 청크 카운트 갱신
            }}
          />
        </div>
      ) : null}
    </Drawer>
  )
}

/* ---- 검색 시험 드로어 (스펙 072·097) — 공유 RetrievalTestDrawer의 컬렉션 어댑터 ----
   메모리 RecallDrawer와 셸을 공유해 UI drift 0. 컬렉션은 enabled 항상 true(비활성 안내는 !ready preAlert). */
function SearchDrawer({
  collection,
  onClose,
  onChanged,
}: {
  collection: Collection | null
  onClose: () => void
  onChanged?: () => void // 히트 편집 저장 후 컬렉션 카운트 갱신(스펙 333)
}) {
  const ready = collection?.status === 'ready'
  // 히트→즉시 편집(스펙 333): 검색해 보니 이 청크/행이 이상함 → 그 자리에서 교정. 히트의
  // document_id로 합성 doc을 만들어 에디터를 열고, locate=히트 텍스트로 그 지점에 선택+스크롤.
  const [editHit, setEditHit] = useState<SearchHit | null>(null)
  return (
    <>
    <RetrievalTestDrawer<SearchHit>
      open={!!collection}
      title={collection ? `검색 시험 · ${collection.name}` : ''}
      scopeKey={collection?.id ?? ''}
      onClose={onClose}
      onSearch={async (q, l) => {
        if (!collection) return { results: [], enabled: true }
        const out = await searchCollection(collection.id, q, l)
        return { results: out.results, enabled: true }
      }}
      hint={
        <>
          에이전트가 채팅에서 쓰는 것과 <b>같은 검색 코어</b>로 이 컬렉션에 질의합니다. 유사도(1.0=동일)
          내림차순으로 상위 청크를 보여줍니다 — 등록한 문서가 의도대로 검색되는지 즉석 확인하세요.
        </>
      }
      preAlert={
        !ready && collection ? (
          <Alert
            type="info"
            showIcon
            title="아직 검색할 청크가 없습니다"
            description="이 컬렉션은 아직 준비되지 않았습니다. 먼저 문서를 올려 처리를 완료하세요."
          />
        ) : null
      }
      queryPlaceholder="예: 환불 정책이 어떻게 되나요?"
      limitLabel="상위 몇 개 (1–10)" // 내부어 top_k 비노출(스펙 252 — 평이한 언어)
      runLabel="검색"
      scoreLabel="유사도"
      countLabel={(n) => `결과 ${n}건`}
      emptyMessage="관련 청크를 찾지 못했습니다."
      emptyQueryWarn="검색어를 입력하세요"
      noResultInfo="관련 청크를 찾지 못했습니다"
      errorFallback="검색에 실패했습니다"
      renderMeta={(h) => (
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)', wordBreak: 'break-all' }}>{h.filename}</span>
      )}
      hitAction={
        collection?.can_manage !== false
          ? (h) =>
              h.document_id ? (
                <Tooltip title="이 내용을 바로 편집합니다 — 바뀐 부분만 다시 임베딩">
                  <Button type="text" size="small" icon={<Icon name="edit" />} onClick={() => setEditHit(h)} />
                </Tooltip>
              ) : null
          : undefined
      }
    />
    {collection ? (
      <DocumentEditorModal
        collectionId={collection.id}
        entity={collection.kind === 'entity'}
        doc={
          editHit?.document_id
            ? ({ id: editHit.document_id, filename: editHit.filename } as RagDocument)
            : null
        }
        locate={editHit?.text}
        onClose={() => setEditHit(null)}
        onSaved={() => {
          onChanged?.()
          message.info('저장됐습니다 — 다시 검색해 반영을 확인하세요')
        }}
      />
    ) : null}
    </>
  )
}

export default function CollectionsView({ onEvaluate }: { onEvaluate?: (cid: string) => void } = {}) {
  const [createOpen, setCreateOpen] = useState(false)
  // 스펙 212: 문서/엔티티 임베딩 탭(데이터 집합 전환 — 탭/세그먼트 규칙상 Tabs). 생성 모달의
  // kind 프리셀렉트에도 이 값을 넘긴다.
  const [kindTab, setKindTab] = useState<'document' | 'entity'>('document')
  const [docsFor, setDocsFor] = useState<Collection | null>(null)
  const [editFor, setEditFor] = useState<Collection | null>(null)
  const [searchFor, setSearchFor] = useState<Collection | null>(null)
  const [reindexFor, setReindexFor] = useState<Collection | null>(null)
  const [confirmDel, setConfirmDel] = useState<Collection | null>(null)
  const [healthFor, setHealthFor] = useState<CollectionHealth | null>(null)
  const [checkingId, setCheckingId] = useState<string | null>(null)

  const { data, loading, reload } = useAsyncData<[Collection[], Model[]]>(
    () => Promise.all([listCollections(), listModels('embedding')]),
    [],
    { errorMsg: '컬렉션을 불러오지 못했습니다' },
  )
  const [collections, models] = data ?? [[], []]
  const loaded = !loading
  // 드로어가 열려 있으면 최신 컬렉션으로 동기화(카운트·설정 갱신).
  useEffect(() => {
    if (!data) return
    const [cs] = data
    setDocsFor((cur) => (cur ? cs.find((c) => c.id === cur.id) ?? cur : cur))
  }, [data])

  const openCreate = () => {
    if (!models.length) {
      message.warning('먼저 임베딩 모델을 등록하세요')
      return
    }
    setCreateOpen(true)
  }

  const submitCreate = async (data: CreateFormData) => {
    const nameErr = validateName(data.name.trim())
    if (nameErr) {
      message.warning(nameErr) // 식별 이름 규칙(스펙 148) — 진실원은 서버 400
      return
    }
    if (!data.embedding_model_id) {
      message.warning('임베딩 모델을 선택하세요')
      return
    }
    // 엔티티 스키마(선택, 스펙 149) — 제출 전 JSON 파싱만 확인(스키마 유효성은 서버 check_schema)
    let entitySchema: Record<string, unknown> | null = null
    if (data.kind === 'entity' && data.schemaText.trim()) {
      try {
        entitySchema = JSON.parse(data.schemaText)
      } catch {
        message.warning('JSON Schema가 올바른 JSON이 아닙니다')
        return
      }
    }
    // 400=모델 누락/임베딩 아님, 409=차원 불일치 또는 이름 중복 — 서버 메시지를 그대로 노출.
    const ok = await runWithToast(() =>
      createCollection({
        name: data.name.trim(),
        kind: data.kind,
        entity_schema: entitySchema,
        description: data.description.trim() || undefined,
        embedding_model_id: data.embedding_model_id,
        chunk_size: data.chunk_size,
        chunk_overlap: data.chunk_overlap,
      }),
    )
    if (ok) {
      reload()
      setCreateOpen(false)
    }
  }

  const doDelete = async () => {
    if (!confirmDel) return
    const ok = await runWithToast(() => deleteCollection(confirmDel.id))
    if (ok) {
      reload()
      setConfirmDel(null)
    }
  }

  const runHealth = async (c: Collection) => {
    if (checkingId) return
    setCheckingId(c.id)
    try {
      setHealthFor(await collectionHealth(c.id))
    } catch (e) {
      message.error(e instanceof Error ? e.message : '점검에 실패했습니다')
    } finally {
      setCheckingId(null)
    }
  }

  const columns: Column<Collection>[] = [
    {
      key: 'name',
      title: '이름',
      render: (c) => (
        // 설명은 상시 노출하지 않고 툴팁으로만(스펙 210 — 리스트=이름 단독, 설명=마우스오버).
        // 스펙 212: kind 배지 제거 — 목록이 이제 탭(문서/엔티티)으로 분리돼 각 탭 내부는 종류가
        // 전부 동일, 배지가 중복 정보가 됐다.
        <div style={{ maxWidth: 260 }}>
          <Tooltip title={c.description || undefined}>
            <span style={{ fontWeight: 500, color: 'var(--color-text-heading)' }}>{c.name}</span>
          </Tooltip>
        </div>
      ),
    },
    {
      key: 'embedding_model_name',
      title: '임베딩 모델',
      hideBelow: 'xl',
      render: (c) => <Tag color="cyan" title={c.embedding_model_name} style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', verticalAlign: 'bottom' }}>{c.embedding_model_name}</Tag>,
    },
    {
      key: 'dims',
      title: '차원',
      width: 80,
      align: 'right',
      render: (c) => <code style={{ ...codeStyle, color: 'var(--color-text-secondary)' }}>{c.dims}</code>,
    },
    {
      key: 'doc_count',
      title: '문서',
      width: 70,
      align: 'right',
      render: (c) => <span style={{ color: 'var(--color-text-secondary)' }}>{c.doc_count}</span>,
    },
    {
      key: 'chunk_count',
      title: '청크',
      width: 70,
      align: 'right',
      hideBelow: 'xl',
      render: (c) => <span style={{ color: 'var(--color-text-secondary)' }}>{c.chunk_count}</span>,
    },
    {
      key: 'status',
      title: '상태',
      width: 110,
      render: (c) => collectionStatusTag(c.status),
    },
    {
      key: 'actions',
      title: '',
      width: 170,
      align: 'right',
      render: (c) => (
        // 검색은 primary로 승격(발견성), 나머지는 아이콘+Tooltip으로 압축 — 액션 컬럼 폭을
        // 줄여(290→170) 데스크탑 테이블이 max-content로 넘쳐 검색 버튼이 가로 스크롤 뒤로
        // 잘리던 문제를 해소(스펙 072 후속). gap으로 아이콘 버튼 간격 확보.
        <span
          onClick={(e) => e.stopPropagation()}
          style={{ display: 'inline-flex', gap: 4, justifyContent: 'flex-end', alignItems: 'center' }}
        >
          {/* 스펙 197 후속: '문서' 버튼 제거 — 행 클릭(onRowClick=setDocsFor)으로 이미 문서 관리가 열려 중복. */}
          <Tooltip title={c.status === 'ready' ? '' : '문서를 인제스트하면 검색할 수 있습니다'}>
            <Button
              type="primary"
              size="small"
              icon={<Icon name="search" />}
              disabled={c.status !== 'ready'}
              onClick={() => setSearchFor(c)}
            >
              검색
            </Button>
          </Tooltip>
          <Tooltip title="점검">
            <Button
              type="text"
              size="small"
              icon={<Icon name="experiment" />}
              loading={checkingId === c.id}
              disabled={checkingId !== null && checkingId !== c.id}
              onClick={() => void runHealth(c)}
            />
          </Tooltip>
          {c.can_manage !== false && (
            <Tooltip title="편집">
              <Button type="text" size="small" icon={<Icon name="edit" />} onClick={() => setEditFor(c)} />
            </Tooltip>
          )}
          {c.can_manage !== false && (
            <Tooltip
              title={
                c.status === 'reindexing'
                  ? '재인덱싱 중'
                  : c.status === 'empty'
                    ? '문서를 올린 뒤 재인덱싱할 수 있습니다'
                    : '재인덱싱 — 임베딩 모델·청크 설정 변경'
              }
            >
              <Button
                type="text"
                size="small"
                icon={<Icon name="sync" />}
                disabled={c.status === 'reindexing' || c.status === 'empty'}
                onClick={() => setReindexFor(c)}
              />
            </Tooltip>
          )}
          {c.can_manage !== false && (
            <Tooltip title="삭제">
              <Button
                type="text"
                size="small"
                danger
                icon={<Icon name="delete" />}
                disabled={c.status === 'reindexing'}
                onClick={() => setConfirmDel(c)}
              />
            </Tooltip>
          )}
        </span>
      ),
    },
  ]

  // 게이트(스펙 048): 임베딩 모델이 하나도 없으면 RAG 메뉴의 모든 동작이 불가능하다 —
  // 컬렉션은 임베딩 모델 FK(RESTRICT) 없이는 만들 수 없고, 문서 업로드는 컬렉션의 바인딩된
  // 모델을 쓴다(모델이 없으면 컬렉션도 없으므로 업로드 경로는 도달 불가). 여기서는 진입점인
  // 생성을 막고 그 이유를 배너로 설명한다. loaded 이전엔 models=[] 초깃값이라 게이트를 끈다
  // (로딩 중 false-positive 배너 플래시 방지, 적대 리뷰 048).
  const noEmbedModel = loaded && !models.length

  return (
    <Page
      title="RAG 컬렉션"
      subtitle="문서를 임베딩해 적재하는 지식 컬렉션 — 문서 인제스트 + 재인덱싱(모델·청크 설정 변경)"
      actions={
        <Tooltip title={noEmbedModel ? '먼저 임베딩 모델을 등록하세요' : ''}>
          <Button
            type="primary"
            icon={<Icon name="plus" />}
            onClick={openCreate}
            disabled={noEmbedModel}
          >
            컬렉션 생성
          </Button>
        </Tooltip>
      }
    >
      {noEmbedModel ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          title="임베딩 모델이 없어 RAG 기능을 사용할 수 없습니다"
          description="컬렉션 생성·문서 적재·검색은 모두 임베딩 모델이 필요합니다. 프로바이더·모델 메뉴에서 '임베딩용' 모델을 먼저 등록하세요."
        />
      ) : null}

      <Tabs
        activeKey={kindTab}
        onChange={(k) => setKindTab(k as 'document' | 'entity')}
        items={[
          {
            key: 'document',
            label: '문서 임베딩',
            children: (
              <DataTable
                columns={columns}
                rows={collections.filter((c) => c.kind === 'document')}
                onRowClick={setDocsFor}
                empty="문서 임베딩 컬렉션이 없습니다"
              />
            ),
          },
          {
            key: 'entity',
            label: '엔티티 임베딩',
            children: (
              <DataTable
                columns={columns}
                rows={collections.filter((c) => c.kind === 'entity')}
                onRowClick={setDocsFor}
                empty="엔티티 임베딩 컬렉션이 없습니다"
              />
            ),
          },
        ]}
      />

      <CreateModal
        open={createOpen}
        models={models}
        initialKind={kindTab}
        onCancel={() => setCreateOpen(false)}
        onSubmit={submitCreate}
      />

      <DocsDrawer collection={docsFor} onClose={() => setDocsFor(null)} onChanged={reload} onEvaluate={onEvaluate} />

      <EditModal collection={editFor} onCancel={() => setEditFor(null)} onSaved={reload} />

      <ReindexModal
        collection={reindexFor}
        models={models}
        onCancel={() => setReindexFor(null)}
        onDone={reload}
      />

      <SearchDrawer collection={searchFor} onClose={() => setSearchFor(null)} onChanged={reload} />

      <Modal
        open={!!confirmDel}
        title="컬렉션을 삭제할까요?"
        okText="삭제"
        cancelText="취소"
        onCancel={() => setConfirmDel(null)}
        onOk={doDelete}
      >
        {confirmDel ? (
          <div>
            <b>{confirmDel.name}</b>을(를) 삭제합니다. 적재된 문서 {confirmDel.doc_count}개와 청크{' '}
            {confirmDel.chunk_count}개가 함께 제거됩니다.
          </div>
        ) : null}
      </Modal>

      <Modal
        open={!!healthFor}
        title="컬렉션 점검"
        footer={[
          <Button key="close" type="primary" onClick={() => setHealthFor(null)}>
            닫기
          </Button>,
        ]}
        onCancel={() => setHealthFor(null)}
      >
        {healthFor ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div
              style={{
                padding: '8px 12px',
                borderRadius: 6,
                fontSize: 14,
                border: `1px solid ${
                  healthFor.consistent ? 'var(--color-success-border)' : 'var(--color-error-border)'
                }`,
                background: healthFor.consistent ? 'var(--color-success-bg)' : 'var(--color-error-bg)',
                color: healthFor.consistent ? 'var(--color-success)' : 'var(--color-error)',
              }}
            >
              {healthFor.consistent ? '✓ 차원 일관성 정상' : '✗ 차원 불일치 — 임베딩 모델과 저장소가 어긋났습니다'}
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Tag>DB 차원: {healthFor.db_dims}</Tag>
              <Tag>컬렉션 차원: {healthFor.collection_dims}</Tag>
              <Tag>모델 차원: {healthFor.model_dims ?? '—'}</Tag>
            </div>
            {healthFor.detail ? (
              <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>{healthFor.detail}</div>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </Page>
  )
}
