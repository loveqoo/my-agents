/* 문서 에디터 모달(스펙 331) — RAG 문서 원문을 런타임에 수정한다.
   에디터=CodeMirror(antd 대응물 없음 — admin CLAUDE.md 예외 규정), **확장자 인식 문법 하이라이트**
   (@codemirror/language-data lazy 매칭: md·py·js·json·yaml 등). 전체화면 Modal 90vw(스펙 192 선례).
   저장하면 그 문서만 재청킹되고 **내용이 같은 청크는 기존 벡터를 재사용**, 바뀐 청크만 재임베딩 —
   결과 통계(청크 n·재임베딩 k·재사용 m)를 토스트로 노출한다. */
import { Alert, Button, Modal, Skeleton, message } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { LanguageDescription } from '@codemirror/language'
import { languages } from '@codemirror/language-data'
import type { Extension } from '@codemirror/state'
import {
  getDocumentContent,
  updateDocumentContent,
  type RagDocument,
} from '../../api'

export function DocumentEditorModal({
  collectionId,
  doc,
  onClose,
  onSaved,
}: {
  collectionId: string
  doc: RagDocument | null // null = 닫힘
  onClose: () => void
  onSaved: () => void // 저장 성공 후(목록·컬렉션 카운트 재조회)
}) {
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [text, setText] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const original = useRef('')
  const [langExt, setLangExt] = useState<Extension | null>(null)

  // 원문 로드 — editable=false는 열지 않고 사유 토스트(버튼 비활성이 1차 방어, 이건 정직 이중화).
  useEffect(() => {
    if (!doc) return
    setLoading(true)
    setLoadError(null)
    setText('')
    original.current = '' // 이전 문서의 원본 잔존 방지(codex 331 P3 — stale dirty로 닫기 확인 오발)
    let alive = true
    getDocumentContent(collectionId, doc.id)
      .then((c) => {
        if (!alive) return
        if (!c.editable || c.text == null) {
          setLoadError(c.reason || '이 문서는 편집할 수 없습니다.')
          return
        }
        original.current = c.text
        setText(c.text)
      })
      .catch((e) => alive && setLoadError(e instanceof Error ? e.message : '원문을 불러오지 못했습니다'))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [collectionId, doc])

  // 확장자 → 문법 하이라이트(lazy load). 미지 확장자는 하이라이트 없이 평문 편집.
  useEffect(() => {
    setLangExt(null)
    if (!doc) return
    const desc = LanguageDescription.matchFilename(languages, doc.filename)
    if (!desc) return
    let alive = true
    void desc.load().then((l) => {
      if (alive) setLangExt(l)
    })
    return () => {
      alive = false
    }
  }, [doc])

  const dirty = text !== original.current
  const extensions = useMemo(() => (langExt ? [langExt] : []), [langExt])

  const requestClose = () => {
    if (saving) return
    if (!dirty) return onClose()
    Modal.confirm({
      title: '저장하지 않은 변경이 있습니다',
      content: '닫으면 편집한 내용이 사라집니다.',
      okText: '닫기',
      okButtonProps: { danger: true },
      cancelText: '계속 편집',
      onOk: onClose,
    })
  }

  const doSave = async () => {
    if (!doc) return
    setSaving(true)
    try {
      const r = await updateDocumentContent(collectionId, doc.id, text)
      message.success(
        `${doc.filename} 저장 완료 — 청크 ${r.chunks}개 (재임베딩 ${r.reembedded} · 재사용 ${r.reused})`,
      )
      onSaved()
      onClose()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '저장에 실패했습니다')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={!!doc}
      width="90vw"
      style={{ top: 24, maxWidth: 1200 }}
      title={doc ? `문서 편집 · ${doc.filename}` : ''}
      onCancel={requestClose}
      mask={{ closable: false }}
      destroyOnHidden
      footer={[
        <span key="hint" style={{ float: 'left', fontSize: 12, color: 'var(--color-text-tertiary)', lineHeight: '32px' }}>
          저장하면 이 문서가 다시 청킹되고, 내용이 바뀐 부분만 다시 임베딩됩니다.
        </span>,
        <Button key="cancel" onClick={requestClose} disabled={saving}>
          취소
        </Button>,
        <Button
          key="save"
          type="primary"
          onClick={() => void doSave()}
          loading={saving}
          disabled={loading || !!loadError || !dirty || !text.trim()}
        >
          저장
        </Button>,
      ]}
    >
      {loading ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : loadError ? (
        <Alert type="warning" showIcon title={loadError} />
      ) : (
        <div style={{ border: '1px solid var(--color-border)', borderRadius: 8, overflow: 'hidden' }}>
          <CodeMirror
            value={text}
            height="65vh"
            extensions={extensions}
            onChange={(v) => setText(v)}
            basicSetup={{ lineNumbers: true, foldGutter: true, highlightActiveLine: true }}
          />
        </div>
      )}
    </Modal>
  )
}
