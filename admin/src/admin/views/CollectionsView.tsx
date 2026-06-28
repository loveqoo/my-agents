/* my-agents admin — RAG 컬렉션 + 문서 인제스트 뷰 (스펙 036).
   컬렉션(임베딩 모델 고정 + 청크 정책) 생성 → 문서 업로드(인제스트 write path) →
   상태/건강 점검. 검색·질의(retrieval) UI는 후속 스펙 — 여기서는 다루지 않는다.
   목록/페이지 셸은 shared의 Page/DataTable을 쓰되, 상호작용 컴포넌트는 antd 6를 사용. */
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
  Tooltip,
  Upload,
  Popconfirm,
  message,
} from 'antd'
import type { UploadProps } from 'antd'
import { Page, DataTable, type Column } from '../shared'
import { Icon } from '../icons'
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
  type Collection,
  type RagDocument,
  type CollectionHealth,
  type Model,
} from '../../api'

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
  name: string
  description: string
  embedding_model_id: string
  chunk_size: number
  chunk_overlap: number
}

const blankCreate: CreateFormData = {
  name: '',
  description: '',
  embedding_model_id: '',
  chunk_size: 1000,
  chunk_overlap: 200,
}

function CreateModal({
  open,
  models,
  onCancel,
  onSubmit,
}: {
  open: boolean
  models: Model[]
  onCancel: () => void
  onSubmit: (data: CreateFormData) => void
}) {
  const [f, setF] = useState<CreateFormData>(blankCreate)

  useEffect(() => {
    if (open) {
      // 임베딩 모델이 하나면 기본 선택 — 입력 한 번 덜기.
      setF({ ...blankCreate, embedding_model_id: models.length === 1 ? models[0].id : '' })
    }
  }, [open, models])

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
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>이름</span>
          <Input placeholder="예: 사내 위키" value={f.name} onChange={(e) => set('name', e.target.value)} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>
            설명 <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(선택)</span>
          </span>
          <TextArea
            rows={3}
            placeholder="이 컬렉션에 담길 지식의 내용"
            value={f.description}
            onChange={(e) => set('description', e.target.value)}
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 14, fontWeight: 500 }}>임베딩 모델</span>
          <Select
            value={f.embedding_model_id || undefined}
            onChange={(v) => set('embedding_model_id', v)}
            style={{ width: '100%' }}
            placeholder={models.length ? '임베딩 모델 선택' : '먼저 임베딩 모델을 등록하세요'}
            options={models.map((m) => ({
              label: `${m.name} — ${m.model_id}`,
              value: m.id,
            }))}
          />
          <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
            생성 후 모델과 차원은 변경할 수 없습니다.
          </span>
        </label>
        <div style={{ display: 'flex', gap: 16 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>청크 크기</span>
            <InputNumber
              min={1}
              style={{ width: '100%' }}
              value={f.chunk_size}
              onChange={(v) => set('chunk_size', v ?? blankCreate.chunk_size)}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
            <span style={{ fontSize: 14, fontWeight: 500 }}>청크 겹침</span>
            <InputNumber
              min={0}
              style={{ width: '100%' }}
              value={f.chunk_overlap}
              onChange={(v) => set('chunk_overlap', v ?? blankCreate.chunk_overlap)}
            />
          </label>
        </div>
      </div>
    </Modal>
  )
}

/* ---- 문서 관리 드로어 ---- */
function DocsDrawer({
  collection,
  onClose,
  onChanged,
}: {
  collection: Collection | null
  onClose: () => void
  onChanged: () => void
}) {
  const [docs, setDocs] = useState<RagDocument[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  // 청크 정책·설명 편집 폼.
  const [description, setDescription] = useState('')
  const [chunkSize, setChunkSize] = useState(1000)
  const [chunkOverlap, setChunkOverlap] = useState(200)
  const [savingPolicy, setSavingPolicy] = useState(false)

  const id = collection?.id ?? null

  const loadDocs = async () => {
    if (!id) return
    setLoading(true)
    try {
      setDocs(await listDocuments(id))
    } catch (e) {
      message.error(e instanceof Error ? e.message : '문서를 불러오지 못했습니다')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (collection) {
      setDescription(collection.description ?? '')
      setChunkSize(collection.chunk_size)
      setChunkOverlap(collection.chunk_overlap)
      void loadDocs()
    } else {
      setDocs([])
    }
    /* eslint-disable-next-line */
  }, [collection?.id])

  const doUpload = async (file: File) => {
    if (!id) return
    setUploading(true)
    try {
      const doc = await uploadDocument(id, file)
      if (doc.status === 'error') message.error(doc.error || '인제스트에 실패했습니다')
      else message.success(`${doc.filename} 인제스트 완료`)
      await loadDocs()
      onChanged() // 컬렉션 카운트(문서·청크)도 갱신
    } catch (e) {
      message.error(e instanceof Error ? e.message : '업로드에 실패했습니다')
    } finally {
      setUploading(false)
    }
  }

  const doDeleteDoc = async (docId: string) => {
    if (!id) return
    try {
      await deleteDocument(id, docId)
      await loadDocs()
      onChanged()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '문서 삭제에 실패했습니다')
    }
  }

  const savePolicy = async () => {
    if (!id) return
    setSavingPolicy(true)
    try {
      await updateCollection(id, {
        description,
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
      })
      message.success('컬렉션 설정을 저장했습니다')
      onChanged()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '설정 저장에 실패했습니다')
    } finally {
      setSavingPolicy(false)
    }
  }

  const uploadProps: UploadProps = {
    accept: '.pdf,.txt,.md',
    multiple: true,
    showUploadList: false,
    // 직접 처리 — antd 자동 업로드를 막고 uploadDocument로 보낸다.
    beforeUpload: (file) => {
      void doUpload(file as unknown as File)
      return false
    },
  }

  const columns: Column<RagDocument>[] = [
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
      width: 60,
      align: 'right',
      render: (d) => (
        <Popconfirm
          title="문서를 삭제할까요?"
          okText="삭제"
          cancelText="취소"
          onConfirm={() => void doDeleteDoc(d.id)}
        >
          <Button type="text" size="small" danger icon={<Icon name="delete" />} />
        </Popconfirm>
      ),
    },
  ]

  return (
    <Drawer
      open={!!collection}
      width={640}
      title={collection ? `문서 관리 · ${collection.name}` : ''}
      onClose={onClose}
      destroyOnHidden
    >
      {collection ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* 업로드 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Upload {...uploadProps}>
              <Button type="primary" icon={<Icon name="paper-clip" />} loading={uploading}>
                문서 업로드
              </Button>
            </Upload>
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              PDF와 UTF-8 텍스트(.txt, .md)만 지원합니다.
            </span>
          </div>

          {/* 문서 목록 */}
          <DataTable columns={columns} rows={docs} empty={loading ? '불러오는 중…' : '문서 없음'} />

          {/* 청크 정책·설명 편집 */}
          <div
            style={{
              padding: 16,
              border: '1px solid var(--color-border-secondary)',
              borderRadius: 'var(--radius-lg)',
              background: 'var(--gray-2)',
              display: 'flex',
              flexDirection: 'column',
              gap: 14,
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text-heading)' }}>컬렉션 설정</div>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 500 }}>설명</span>
              <TextArea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
            </label>
            <div style={{ display: 'flex', gap: 16 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
                <span style={{ fontSize: 13, fontWeight: 500 }}>청크 크기</span>
                <InputNumber
                  min={1}
                  style={{ width: '100%' }}
                  value={chunkSize}
                  onChange={(v) => setChunkSize(v ?? collection.chunk_size)}
                />
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
                <span style={{ fontSize: 13, fontWeight: 500 }}>청크 겹침</span>
                <InputNumber
                  min={0}
                  style={{ width: '100%' }}
                  value={chunkOverlap}
                  onChange={(v) => setChunkOverlap(v ?? collection.chunk_overlap)}
                />
              </label>
            </div>
            <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
              청크 정책 변경은 이후 업로드되는 문서에만 적용됩니다. 모델과 차원은 변경할 수 없습니다.
            </span>
            <Button onClick={() => void savePolicy()} loading={savingPolicy} style={{ alignSelf: 'flex-start' }}>
              설정 저장
            </Button>
          </div>
        </div>
      ) : null}
    </Drawer>
  )
}

export default function CollectionsView() {
  const [collections, setCollections] = useState<Collection[]>([])
  const [models, setModels] = useState<Model[]>([])
  const [loaded, setLoaded] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [docsFor, setDocsFor] = useState<Collection | null>(null)
  const [confirmDel, setConfirmDel] = useState<Collection | null>(null)
  const [healthFor, setHealthFor] = useState<CollectionHealth | null>(null)
  const [checkingId, setCheckingId] = useState<string | null>(null)

  const load = async () => {
    try {
      const [cs, ms] = await Promise.all([listCollections(), listModels('embedding')])
      setCollections(cs)
      setModels(ms)
      // 드로어가 열려 있으면 최신 컬렉션으로 동기화(카운트·설정 갱신).
      setDocsFor((cur) => (cur ? cs.find((c) => c.id === cur.id) ?? cur : cur))
    } catch (e) {
      message.error(e instanceof Error ? e.message : '컬렉션을 불러오지 못했습니다')
    } finally {
      setLoaded(true)
    }
  }

  useEffect(() => {
    void load()
    /* eslint-disable-next-line */
  }, [])

  const openCreate = () => {
    if (!models.length) {
      message.warning('먼저 임베딩 모델을 등록하세요')
      return
    }
    setCreateOpen(true)
  }

  const submitCreate = async (data: CreateFormData) => {
    if (!data.name.trim()) {
      message.warning('이름을 입력하세요')
      return
    }
    if (!data.embedding_model_id) {
      message.warning('임베딩 모델을 선택하세요')
      return
    }
    try {
      await createCollection({
        name: data.name.trim(),
        description: data.description.trim() || undefined,
        embedding_model_id: data.embedding_model_id,
        chunk_size: data.chunk_size,
        chunk_overlap: data.chunk_overlap,
      })
      await load()
      setCreateOpen(false)
    } catch (e) {
      // 400=모델 누락/임베딩 아님, 409=차원 불일치 또는 이름 중복 — 서버 메시지를 그대로 노출.
      message.error(e instanceof Error ? e.message : '컬렉션 생성에 실패했습니다')
    }
  }

  const doDelete = async () => {
    if (!confirmDel) return
    try {
      await deleteCollection(confirmDel.id)
      await load()
      setConfirmDel(null)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '삭제에 실패했습니다')
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
        <div>
          <span style={{ fontWeight: 500, color: 'var(--color-text-heading)' }}>{c.name}</span>
          {c.description ? (
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)', marginTop: 2 }}>{c.description}</div>
          ) : null}
        </div>
      ),
    },
    {
      key: 'embedding_model_name',
      title: '임베딩 모델',
      render: (c) => <Tag color="cyan">{c.embedding_model_name}</Tag>,
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
      width: 220,
      align: 'right',
      render: (c) => (
        <span onClick={(e) => e.stopPropagation()}>
          <Button type="text" size="small" icon={<Icon name="file" />} onClick={() => setDocsFor(c)}>
            문서
          </Button>
          <Button
            type="text"
            size="small"
            icon={<Icon name="experiment" />}
            loading={checkingId === c.id}
            disabled={checkingId !== null && checkingId !== c.id}
            onClick={() => void runHealth(c)}
          >
            점검
          </Button>
          <Button type="text" size="small" danger icon={<Icon name="delete" />} onClick={() => setConfirmDel(c)} />
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
      subtitle="문서를 임베딩해 적재하는 지식 컬렉션 — 모델·청크 정책 고정 + 문서 인제스트"
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
          description="컬렉션 생성·문서 적재·검색은 모두 임베딩 모델이 필요합니다. 프로바이더·모델 메뉴에서 임베딩 종류(kind=embedding) 모델을 먼저 등록하세요."
        />
      ) : null}

      <DataTable columns={columns} rows={collections} onRowClick={setDocsFor} />

      <CreateModal
        open={createOpen}
        models={models}
        onCancel={() => setCreateOpen(false)}
        onSubmit={submitCreate}
      />

      <DocsDrawer collection={docsFor} onClose={() => setDocsFor(null)} onChanged={load} />

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
