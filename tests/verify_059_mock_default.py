"""스펙 059 검증 — MLX env 탈피·Mock LLM 기본화·실 모델은 Provider UI.

사용자가 외부(라이브 인프라 어려움)라 **정적/단위**로만 검증한다(스펙 059 §완료조건). DB·모델서버
없이: 시드 소스 단언, 마이그레이션 소스 단언, env/문서 파일 스캔, agent CLI/스키마 import 단언.

검증(설계 D1~D6 매핑):
  D2 seed: CHAT_MODEL_NAME=='mock-llm'; Provider 시드 블록이 MLX-free·Mock 하나만; mock-llm(chat,
      is_default,model_id=mock-chat)+mock-embed(embedding,is_default,model_id=mock-embed) 시드;
      에이전트가 CHAT_MODEL_NAME을 참조 → 댕글링 없음; 컬렉션이 mock-embed에 바인딩.
  D1 migration: down_revision=head(b7c8d9e0f1a2); mock-llm 없으면 무동작; **기본 chat 있으면 승격
      안 함**(no-clobber); mock-embed 멱등(이름 존재 시 skip)+기본 없을 때만 default; downgrade 가역.
  D3 .env.example: MLX_ env 0건; Mock 기본 안내 존재.
  D4 agent/스키마: agent CLI가 MODEL_* env(벤더 무관)·MLX_ 0건; models.py/schemas.py 기본 'mock-llm'.
  D5 chat.py: 힌트가 '기본은 MLX' 제거·Mock LLM 되돌리기 안내 유지(연결지문 감지 무회귀).
  D6 README: MLX_* 테이블 행 제거; Mock 기본 안내 존재.

실행: uv run python tests/verify_059_mock_default.py   (or: .venv/bin/python)
전제: 없음(라이브 DB/모델 불필요). import만 되면 동작.
"""

import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))
sys.path.insert(0, os.path.join(ROOT, "packages", "agent", "src"))

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def main() -> None:
    from api import seed, chat, schemas, models as api_models  # noqa: E402
    from agent import main as agent_main  # noqa: E402

    # ── D2. seed: 단일 소스 이름 + Mock-only provider 블록 ──────────────────────
    check(seed.CHAT_MODEL_NAME == "mock-llm",
          f"D2 CHAT_MODEL_NAME=='mock-llm' (실제={seed.CHAT_MODEL_NAME!r})")
    ssrc = inspect.getsource(seed.seed_if_empty) if hasattr(seed, "seed_if_empty") \
        else inspect.getsource(seed)
    # Provider 시드 블록에 MLX 결합이 없어야 한다(이름·env 모두).
    check("MLX_BASE_URL" not in ssrc and "MLX_API_KEY" not in ssrc and "MLX_MODEL" not in ssrc,
          "D2 seed에 MLX_* env 결합 없음")
    check("local-mlx" not in ssrc, "D2 seed에 'local-mlx' 잔재 없음")
    # Mock provider 1개 + 두 모델(chat/embed) 시드.
    check('name="Mock LLM"' in ssrc and 'kind="mock"' in ssrc,
          "D2 Mock LLM provider(kind=mock) 시드")
    check('model_id="mock-chat"' in ssrc and 'kind="chat"' in ssrc and "is_default=True" in ssrc,
          "D2 mock-chat 채팅 모델 is_default 시드")
    check('name="mock-embed"' in ssrc and 'model_id="mock-embed"' in ssrc
          and 'kind="embedding"' in ssrc,
          "D2 mock-embed 임베딩 모델 시드")
    # 에이전트 모델 참조가 CHAT_MODEL_NAME 단일 소스 → 시드 chat 모델 이름과 일치(댕글링 0).
    check("CHAT_MODEL_NAME" in ssrc and ssrc.count("CHAT_MODEL_NAME") >= 3,
          "D2 시드 에이전트가 CHAT_MODEL_NAME 참조(단일 소스, 댕글링 없음)")
    # 컬렉션은 mock-embed에 바인딩(임베딩 부재 크래시 방지).
    check('"mock-embed"' in ssrc, "D2 컬렉션 기본 임베딩이 mock-embed")

    # ── D1. migration: head 위 + no-clobber + 멱등 + 가역 ───────────────────────
    mig = _read("packages/api/alembic/versions/c9d0e1f2a3b4_mock_default_and_embed.py")
    check('down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"' in mig,
          "D1 down_revision이 직전 head(b7c8d9e0f1a2)")
    check("if row is None:" in mig and "return" in mig,
          "D1 mock-llm 부재 시 무동작(예외 상태 비침습)")
    # no-clobber: chat 기본이 이미 있으면 승격 안 함.
    check("has_default_chat" in mig and "if not has_default_chat:" in mig,
          "D1 기존 chat 기본 보존(default 있으면 mock 승격 안 함 — no-clobber)")
    upg = mig[mig.index("def upgrade"):mig.index("def downgrade")]
    set_def = upg.index("SET is_default = true WHERE id = :id")
    guard = upg.index("if not has_default_chat:")
    check(guard < set_def, "D1 no-clobber 가드가 승격 발행 *앞*")
    # mock-embed 멱등: 이름 존재 시 skip.
    check("embed_exists" in mig and "if not embed_exists:" in mig,
          "D1 mock-embed 멱등(이름 존재 시 INSERT skip)")
    check("has_default_embed" in mig,
          "D1 임베딩 기본도 '없을 때만' default(임베딩 no-clobber)")
    # 가역 downgrade.
    dwn = mig[mig.index("def downgrade"):]
    check("DELETE FROM models WHERE name = 'mock-embed'" in dwn,
          "D1 downgrade가 mock-embed 제거")
    check("SET is_default = false WHERE name = 'mock-llm'" in dwn,
          "D1 downgrade가 mock-llm chat 기본 해제(가역)")

    # ── D3. .env.example: MLX env 제거 + Mock 안내 ─────────────────────────────
    env = _read(".env.example")
    check("MLX_BASE_URL" not in env and "MLX_API_KEY" not in env and "MLX_MODEL" not in env,
          "D3 .env.example에 MLX_* env 0건")
    check("Mock LLM" in env and "Provider UI" in env,
          "D3 .env.example에 Mock 기본 + Provider UI 안내")

    # ── D4. agent CLI + 스키마/모델 기본값 ──────────────────────────────────────
    asrc = inspect.getsource(agent_main.main)
    check("MODEL_BASE_URL" in asrc and "MODEL_ID" in asrc,
          "D4 agent CLI가 벤더무관 MODEL_* env 사용")
    full_agent = inspect.getsource(agent_main)
    check("MLX_BASE_URL" not in full_agent and "MLX_API_KEY" not in full_agent
          and "MLX_MODEL" not in full_agent,
          "D4 agent 패키지에 MLX_* env 0건")
    check(schemas.AgentConfig().model == "mock-llm",
          f"D4 AgentConfig.model 기본 'mock-llm' (실제={schemas.AgentConfig().model!r})")
    # models.py Agent.model 컬럼 기본값.
    msrc = inspect.getsource(api_models)
    check('default="mock-llm"' in msrc, "D4 Agent.model 컬럼 기본 'mock-llm'")
    check("local-mlx" not in msrc, "D4 models.py에 'local-mlx' 잔재 없음")

    # ── D5. chat.py 힌트 재작성(무회귀 연결지문) ────────────────────────────────
    hsrc = inspect.getsource(chat._model_error_hint)
    check("기본은 MLX" not in hsrc and "MLX_BASE_URL" not in hsrc,
          "D5 힌트에서 'MLX 기본' 안내 제거")
    check("Mock LLM" in hsrc, "D5 힌트가 Mock LLM 되돌리기 안내 유지")
    # 무회귀: 연결지문 감지/마커는 그대로.
    cfg = {"base_url": "http://localhost:8045/v1", "model_id": "x"}
    h = chat._model_error_hint(Exception("All connection attempts failed"), cfg)
    check(h is not None and "Mock LLM" in h and "http://localhost:8045/v1" in h,
          "D5 연결실패+cfg → Mock LLM 힌트(base_url 포함, 무회귀)")
    check(chat._model_error_hint(Exception("model not found (404)"), cfg) is None,
          "D5 비연결오류(404)는 힌트 없음(무회귀)")
    check(chat._model_error_hint(Exception("x"), None) is None,
          "D5 model_cfg 없으면 힌트 없음(무회귀)")

    # ── D6. README: MLX 행 제거 + Mock 기본 안내 ───────────────────────────────
    rm = _read("README.md")
    check("`MLX_BASE_URL` / `MLX_API_KEY` / `MLX_MODEL`" not in rm,
          "D6 README 환경변수 표에서 MLX_* 행 제거")
    check("Mock LLM" in rm and "Provider UI" in rm,
          "D6 README에 Mock 기본 + Provider UI 안내")

    print()
    if _fails:
        print(f"FAILED {len(_fails)}건:")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS — VERIFY059_OK")


if __name__ == "__main__":
    main()
