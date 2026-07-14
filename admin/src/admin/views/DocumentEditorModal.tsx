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
import { EditorSelection } from '@codemirror/state'
import type { EditorView } from '@codemirror/view'
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
  entity = false,
  locate,
  locateLine,
}: {
  collectionId: string
  doc: RagDocument | null // null = 닫힘
  onClose: () => void
  onSaved: () => void // 저장 성공 후(목록·컬렉션 카운트 재조회)
  entity?: boolean // 엔티티 컬렉션(스펙 332) — JSONL 행 단위 힌트·json 하이라이트
  locate?: string // 열리자마자 이 텍스트(검색 히트)를 찾아 선택+스크롤(스펙 333). 못 찾으면 그냥 열림
  // n번째 비어있지 않은 줄을 통째 선택(스펙 337 — 엔티티 히트의 결정적 좌표). 객체 data 행은
  // 히트 텍스트가 평탄화 결과라 원본 JSONL에 없어 텍스트 매칭이 항상 실패했다 — 좌표가 정답.
  locateLine?: number | null
}) {
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [text, setText] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const original = useRef('')
  const [langExt, setLangExt] = useState<Extension | null>(null)
  const viewRef = useRef<EditorView | null>(null)

  // 히트 텍스트로 정밀 진입(스펙 333) — 원문 로드+에디터 생성이 둘 다 끝난 뒤 1회 실행.
  // 엔티티는 JSONL 라인 안에서 이스케이프될 수 있어 후보 2개(원문·JSON 이스케이프 내부형)로 탐색.
  const locatedFor = useRef<string | null>(null)
  const tryLocate = () => {
    const view = viewRef.current
    const wantLine = locateLine != null && locateLine >= 0
    if (!view || (!locate && !wantLine) || !original.current || locatedFor.current === original.current)
      return
    const body = view.state.doc.toString()
    if (wantLine) {
      // 줄 좌표 경로(스펙 337) — 파서(parse_entity_lines)와 같은 규칙으로 빈 줄을 건너뛰며
      // n번째 비어있지 않은 줄을 찾는다(ordinal ↔ 줄 대응 보존).
      locatedFor.current = original.current
      let idx = -1
      let pos = 0
      for (const line of body.split('\n')) {
        if (line.trim()) idx += 1
        if (idx === locateLine) {
          view.dispatch({
            selection: EditorSelection.range(pos, pos + line.length),
            scrollIntoView: true,
          })
          view.focus()
          return
        }
        pos += line.length + 1
      }
      return // 좌표 밖(편집으로 행이 줄었거나) — 우아한 강등
    }
    // 후보 3: 원문 / JSON 이스케이프 내부형(따옴표·역슬래시) / ASCII \uXXXX 전량 이스케이프
    // (codex 333 P2 — ensure_ascii 계열 파이프라인이 만든 JSONL은 비ASCII가 escape로 저장됨).
    if (!locate) return
    const jsonInner = JSON.stringify(locate).slice(1, -1)
    const asciiEscaped = jsonInner.replace(
      /[\u0080-\uffff]/g,
      (ch) => '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0'),
    )
    const candidates = [locate, jsonInner, asciiEscaped]
    const found = candidates.map((c) => ({ c, i: body.indexOf(c) })).find((x) => x.i >= 0)
    locatedFor.current = original.current // 재시도 방지(편집 중 커서 탈취 금지)
    if (!found) return // 우아한 강등 — 그냥 열림
    view.dispatch({
      selection: EditorSelection.range(found.i, found.i + found.c.length),
      scrollIntoView: true,
    })
    view.focus()
  }
  useEffect(() => {
    if (!doc) locatedFor.current = null
    tryLocate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, text, locate, locateLine])

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
  // .jsonl은 language-data에 없어 json으로 수동 매핑(스펙 332 — 엔티티 원본).
  useEffect(() => {
    setLangExt(null)
    if (!doc) return
    const name = /\.jsonl$/i.test(doc.filename) ? 'rows.json' : doc.filename
    const desc = LanguageDescription.matchFilename(languages, name)
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
          {entity
            ? '한 줄 = 한 엔티티(JSONL). 저장하면 바뀐 행만 다시 임베딩됩니다 — 원본은 파이프라인 재업로드가 덮을 수 있어 임시 교정 용도입니다.'
            : '저장하면 이 문서가 다시 청킹되고, 내용이 바뀐 부분만 다시 임베딩됩니다.'}
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
            onCreateEditor={(view) => {
              viewRef.current = view
              tryLocate() // 에디터가 로드보다 늦게 생성되는 순서 커버(스펙 333)
            }}
            basicSetup={{ lineNumbers: true, foldGutter: true, highlightActiveLine: true }}
          />
        </div>
      )}
    </Modal>
  )
}
