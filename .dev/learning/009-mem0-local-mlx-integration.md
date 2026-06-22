# 009 — Mem0를 로컬 MLX로 구성하기 (LLM·임베딩·벡터스토어)

날짜: 2026-06-23
맥락: [docs/spec/007](../../docs/spec/007-real-agent-service.md) Phase 2, `packages/api/src/api/memory.py`

## 핵심
mem0(`mem0ai==2.0.7`)를 외부 OpenAI 없이 **전부 로컬**로 돌릴 수 있다.

1. **임베딩 모델은 LLM과 별개다.** 우리 MLX 서버는 `/v1/embeddings`를 제공하지만
   채팅 모델이 아니라 **별도 임베딩 모델**(`--embedding-model`)로만 동작한다.
   - 확인: `curl /v1/embeddings -d '{"model":"<chat-model>","input":"..."}'` →
     서버가 "Only 'mlx-community/multilingual-e5-large-mlx' can be used" 라고 알려줌.
   - 그래서 mem0 embedder는 임베딩 전용 모델명(`multilingual-e5-large-mlx`, **1024차원**)을 써야 함.
2. **mem0 config** (`Memory.from_config`):
   - `llm`: provider `openai`, config `{model: <MLX chat>, openai_base_url, api_key}`
   - `embedder`: provider `openai`, config `{model: <MLX embed>, openai_base_url, api_key, embedding_dims: 1024}`
   - `vector_store`: provider `qdrant`, config `{path: <local dir>, embedding_model_dims: 1024, on_disk: True}`
     → **임베디드 qdrant(on-disk)** 로 별도 서버 불필요. (서버 6333 안 띄워도 됨)
   - 안전벨트로 `OPENAI_API_KEY`/`OPENAI_BASE_URL` env도 같이 설정.
3. **mem0 2.x API 변경**: `search()`는 `user_id=` 가 deprecated →
   **`filters={"user_id": ...}`** 사용. (`add()`는 여전히 `user_id=` 허용)
   - 증상: "Top-level entity parameters frozenset({'user_id'}) are not supported in search(). Use filters=..."
4. **spaCy 경고**는 무해(선택적 NLP). 무시 가능.

## 적용 패턴
- 통합은 **try/except로 감싸 graceful 무력화**: init 실패/호출 실패 시 메모리만 끄고 채팅은 계속.
- mem0 호출은 동기 → FastAPI async에서는 `await asyncio.to_thread(...)`로 이벤트 루프 보호.
- 검증: 1차 대화에서 `add` → 2차 대화에서 `search`가 의미적 회상(score 0.84) → 실제로 돈다.

## 주의 (추후)
- `_get_memory()`를 `lru_cache`로 1회 캐시 → init 실패가 프로세스 수명 내내 고정(재시도 없음).
  운영에선 TTL 재시도 고려.
- 임베디드 qdrant는 경로를 한 프로세스가 잠금 — 멀티 워커 시 외부 qdrant로.
