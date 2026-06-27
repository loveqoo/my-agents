"""RAG 인제스트 파이프라인 헬퍼 — 파싱 → 청킹 → 임베딩 (스펙 036).

쓰기 경로만 담당. retrieval(질의·유사도 검색)은 037.
- 파싱: PDF는 pypdf, 그 외는 UTF-8 텍스트로 디코드.
- 청킹: langchain RecursiveCharacterTextSplitter(컬렉션별 chunk_size/overlap).
- 임베딩: OpenAI 호환 `/embeddings` 배치 호출(provider base_url/복호화 키).
"""

import io

import httpx
from langchain_text_splitters import RecursiveCharacterTextSplitter


class IngestError(Exception):
    """인제스트 실패 — 메시지를 Document.error에 보존(no silent death)."""


def extract_text(filename: str, content_type: str | None, data: bytes) -> str:
    """업로드 바이트에서 평문 추출. PDF는 pypdf, 그 외는 UTF-8 디코드.

    이미지 PDF·OCR·기타 형식(docx/html)은 범위 밖 — 텍스트가 안 나오면 IngestError.
    """
    is_pdf = (content_type or "").lower().endswith("pdf") or filename.lower().endswith(".pdf")
    if is_pdf:
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            pages = [(page.extract_text() or "") for page in reader.pages]
        except Exception as exc:  # noqa: BLE001 — 손상 PDF 등
            raise IngestError(f"PDF 파싱 실패: {exc}") from exc
        text = "\n\n".join(p for p in pages if p.strip())
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestError("UTF-8 텍스트로 디코드할 수 없습니다(지원 형식: PDF·UTF-8 텍스트).") from exc
    if not text.strip():
        raise IngestError("문서에서 추출된 텍스트가 없습니다(이미지 전용 PDF 등은 미지원).")
    return text


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """RecursiveCharacterTextSplitter로 컬렉션 설정에 따라 분할. 빈 청크 제거."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=max(1, chunk_size),
        chunk_overlap=max(0, min(chunk_overlap, max(0, chunk_size - 1))),
        separators=["\n\n", "\n", " ", ""],
    )
    return [c for c in splitter.split_text(text) if c.strip()]


async def embed_texts(
    base_url: str, api_key: str | None, model_id: str, texts: list[str]
) -> list[list[float]]:
    """OpenAI 호환 `/embeddings` 배치 호출 → 입력 순서대로 벡터 리스트.

    응답 `data`는 index 필드로 정렬 보장. 실패 시 IngestError(비밀 미포함 메시지).
    """
    if not texts:
        return []
    if not base_url:
        raise IngestError("임베딩 provider base_url이 없습니다.")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = base_url.rstrip("/") + "/embeddings"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, headers=headers, json={"model": model_id, "input": texts})
    except Exception as exc:  # noqa: BLE001 — 네트워크 오류(상세 미노출)
        raise IngestError("임베딩 서버 연결 실패") from exc
    if r.status_code != 200:
        # 본문은 키를 에코할 수 있어 상태코드만 노출.
        raise IngestError(f"임베딩 HTTP {r.status_code}")
    try:
        data = r.json().get("data") or []
        ordered = sorted(data, key=lambda d: d.get("index", 0))
        vectors = [d.get("embedding") or [] for d in ordered]
    except Exception as exc:  # noqa: BLE001
        raise IngestError("임베딩 응답 파싱 실패") from exc
    if len(vectors) != len(texts) or any(not v for v in vectors):
        raise IngestError("임베딩 응답이 입력 청크 수와 맞지 않습니다.")
    # index 정합 — 중복·누락 index면 정렬을 신뢰할 수 없어 text↔vector가 조용히 어긋난다.
    # 정확히 0..n-1이어야 위 sorted() 정렬이 입력 순서를 복원한다고 보장된다.
    idxs = [d.get("index") for d in data]
    if any(i is None for i in idxs) or sorted(idxs) != list(range(len(texts))):
        raise IngestError("임베딩 응답 index가 0..n-1과 정확히 일치하지 않습니다(정렬 신뢰 불가).")
    return vectors
