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


def _reject_nonstandard_const(name: str) -> None:
    """json.loads parse_constant 훅 — NaN/Infinity/-Infinity 거부(표준 JSON 아님·JSONB 저장 불가)."""
    raise ValueError(f"비표준 JSON 상수({name})는 허용되지 않습니다")


def is_pdf(filename: str, content_type: str | None) -> bool:
    """PDF 판별(단일 출처) — 추출(extract_text)과 편집 가능 판정(스펙 331)이 같은 기준을 공유해야
    'PDF인데 편집 허용' 같은 드리프트가 없다."""
    return (content_type or "").lower().endswith("pdf") or filename.lower().endswith(".pdf")


def extract_text(filename: str, content_type: str | None, data: bytes) -> str:
    """업로드 바이트에서 평문 추출. PDF는 pypdf, 그 외는 UTF-8 디코드.

    이미지 PDF·OCR·기타 형식(docx/html)은 범위 밖 — 텍스트가 안 나오면 IngestError.
    """
    if is_pdf(filename, content_type):
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            pages = [(page.extract_text() or "") for page in reader.pages]
        except Exception as exc:
            raise IngestError(f"PDF 파싱 실패: {exc}") from exc
        text = "\n\n".join(p for p in pages if p.strip())
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestError(
                "UTF-8 텍스트로 디코드할 수 없습니다(지원 형식: PDF·UTF-8 텍스트)."
            ) from exc
    if not text.strip():
        raise IngestError("문서에서 추출된 텍스트가 없습니다(이미지 전용 PDF 등은 미지원).")
    return text


# ----------------------------- 엔티티 인제스트 (스펙 149) -----------------------------
# JSONL 행 단위: {"metadata": {...id들}, "data": {...임베딩 소스} | "문자열"} — 1행=1청크(분할 없음).
ENTITY_MAX_ROWS = 5000  # 파일당 행 수 캡 — 초과 시 400(조용한 축소 금지)
ENTITY_MAX_TEXT_CHARS = 8000  # 행당 임베딩 텍스트 캡 — 초과 시 400(임베딩 입력 한계)
ENTITY_MAX_META_CHARS = 2000  # 행당 metadata 직렬화 캡(codex 149 — 검색 응답 비대 방지)


class EntityParseError(IngestError):
    """엔티티 JSONL 형식 위반 — fail-closed(파일 전체 거부). 소스가 SQL 추출물이라 위반=파이프라인
    버그이며, 부분 스킵은 비즈니스 데이터의 조용한 유실이다. 메시지에 행 번호를 포함한다."""


def entity_text(data: object) -> str:
    """임베딩 텍스트 직렬화 — 문자열은 그대로, 객체는 `key: value` 줄 평탄화(중첩 값은 JSON).
    키 순서는 입력 순서 보존(사용자의 SELECT 컬럼 순서가 곧 의미 순서). 순수 함수."""
    import json as _json

    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        lines = []
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                v = _json.dumps(v, ensure_ascii=False)
            lines.append(f"{k}: {v}")
        return "\n".join(lines).strip()
    return ""


def parse_entity_lines(raw: bytes, schema: dict | None = None) -> list[tuple[str, dict]]:
    """JSONL 바이트 → [(임베딩 텍스트, metadata)] — fail-closed(위반 행=EntityParseError, 행 번호 포함).

    행 계약: JSON 객체 + `metadata`(객체) + `data`(객체|문자열, 직렬화 후 비어있지 않음).
    schema 지정 시 각 행 전체를 JSON Schema로 검증(내용물 드리프트 차단 — SQL 변경으로 id 누락 등).
    빈 줄은 무시(후행 개행 허용). 순수 함수(DB/네트워크 없음)."""
    import json as _json

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EntityParseError("UTF-8 텍스트가 아닙니다 — JSONL(UTF-8) 파일을 올려주세요.") from exc

    validator = None
    if schema is not None:
        import jsonschema

        validator = jsonschema.Draft202012Validator(schema)

    rows: list[tuple[str, dict]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue  # 빈 줄 허용(후행 개행 등)
        # 캡 검사를 파싱 **앞**에(codex 149 Low) — 5001번째 행의 파싱/스키마 검증 비용도 쓰지 않는다.
        if len(rows) >= ENTITY_MAX_ROWS:
            raise EntityParseError(f"행이 {ENTITY_MAX_ROWS}개를 넘습니다 — 파일을 나눠 올려주세요.")
        try:
            # parse_constant — NaN/Infinity는 표준 JSON이 아니고 JSONB insert에서 500으로 터진다
            # (codex 332 P2, 업로드·편집 두 입구 공통 봉인). ValueError는 아래서 행 번호로 감싸진다.
            obj = _json.loads(line, parse_constant=_reject_nonstandard_const)
        except ValueError as exc:
            raise EntityParseError(f"{lineno}번째 줄: JSON 파싱 실패 — {exc}") from exc
        if not isinstance(obj, dict):
            raise EntityParseError(
                f"{lineno}번째 줄: JSON 객체가 아닙니다(계약: {{metadata, data}})."
            )
        meta = obj.get("metadata")
        if not isinstance(meta, dict):
            raise EntityParseError(f"{lineno}번째 줄: metadata가 객체가 아닙니다.")
        data = obj.get("data")
        if not isinstance(data, (dict, str)):
            raise EntityParseError(f"{lineno}번째 줄: data는 객체 또는 문자열이어야 합니다.")
        if validator is not None:
            err = next(iter(validator.iter_errors(obj)), None)
            if err is not None:
                path = "/".join(str(p) for p in err.absolute_path) or "(루트)"
                raise EntityParseError(
                    f"{lineno}번째 줄: 스키마 위반 — {path}: {err.message[:200]}"
                )
        txt = entity_text(data)
        if not txt:
            raise EntityParseError(f"{lineno}번째 줄: data에서 임베딩할 텍스트가 없습니다.")
        if len(txt) > ENTITY_MAX_TEXT_CHARS:
            raise EntityParseError(
                f"{lineno}번째 줄: 텍스트가 {len(txt)}자 — 행당 최대 {ENTITY_MAX_TEXT_CHARS}자입니다."
            )
        mlen = len(_json.dumps(meta, ensure_ascii=False))
        if mlen > ENTITY_MAX_META_CHARS:
            raise EntityParseError(
                f"{lineno}번째 줄: metadata가 {mlen}자 — 행당 최대 {ENTITY_MAX_META_CHARS}자입니다."
            )
        rows.append((txt, meta))
    if not rows:
        raise EntityParseError("적재할 행이 없습니다(빈 파일).")
    return rows


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
    except Exception as exc:
        raise IngestError("임베딩 서버 연결 실패") from exc
    if r.status_code != 200:
        # 본문은 키를 에코할 수 있어 상태코드만 노출.
        raise IngestError(f"임베딩 HTTP {r.status_code}")
    try:
        data = r.json().get("data") or []
        ordered = sorted(data, key=lambda d: d.get("index", 0))
        vectors = [d.get("embedding") or [] for d in ordered]
    except Exception as exc:
        raise IngestError("임베딩 응답 파싱 실패") from exc
    if len(vectors) != len(texts) or any(not v for v in vectors):
        raise IngestError("임베딩 응답이 입력 청크 수와 맞지 않습니다.")
    # index 정합 — 중복·누락 index면 정렬을 신뢰할 수 없어 text↔vector가 조용히 어긋난다.
    # 정확히 0..n-1이어야 위 sorted() 정렬이 입력 순서를 복원한다고 보장된다.
    idxs = [d.get("index") for d in data]
    if any(i is None for i in idxs) or sorted(idxs) != list(range(len(texts))):
        raise IngestError("임베딩 응답 index가 0..n-1과 정확히 일치하지 않습니다(정렬 신뢰 불가).")
    return vectors
