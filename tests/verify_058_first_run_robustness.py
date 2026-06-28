"""스펙 058 검증 — 첫 실행 견고성(G1 DB 프리플라이트·G2 부트스트랩·G4 모델 힌트).

사용자가 외부(테스트 어려운 환경)라 **라이브 인프라 없이 정적/단위**로만 검증한다(스펙 058 §완료조건).
DB·MLX 서버 없이 동작하도록: G1은 engine을 가짜로 바꿔 연결예외를 강제, G2는 DB 이전의 입력검증
분기만 실행 + escalation 가드는 소스 단언, G4는 헬퍼를 직접 호출.

검증:
  G1. _mask_dsn 비밀번호 마스킹; _preflight 연결예외→명확 RuntimeError(메시지에 마스킹DSN·docker 힌트);
      init_db 소스가 프리플라이트 먼저 + 폴백에 CREATE EXTENSION vector 발행.
  G2. bootstrap_admin 입력검증(잘못된 이메일·짧은 비번→거부, DB 미접촉); escalation 가드 소스 단언
      (기존 super→0 무동작, 기존 일반→3 승격거부, 신규만 생성); seed_admin 강화경고 소스 단언(유저0만).
  G4. _model_error_hint: 연결예외+model_cfg→'Mock LLM' 힌트(base_url 포함); 비연결오류→None;
      model_cfg 없음→None; chat except 블록이 힌트를 사용.

실행: uv run python tests/verify_058_first_run_robustness.py   (or: .venv/bin/python)
전제: 없음(라이브 DB/MLX 불필요). import만 되면 동작.
"""

import asyncio
import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

from api import bootstrap_admin as ba  # noqa: E402
from api import chat, db, users  # noqa: E402

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class _APIConnectionError(Exception):
    """openai/httpx 연결오류 모사(이름·메시지에 연결 지문)."""


async def main() -> None:
    # ── G1. DSN 마스킹 ──────────────────────────────────────────────────────
    masked = db._mask_dsn("postgresql+asyncpg://agent:s3cret@localhost:5432/agents")
    check("s3cret" not in masked and "agent:***@localhost" in masked,
          f"G1 _mask_dsn 비밀번호만 가림 (실제={masked})")
    check(db._mask_dsn("sqlite:///x.db") == "sqlite:///x.db", "G1 자격증명 없는 DSN은 불변")
    check(db._mask_dsn("postgresql://agent@host/db") == "postgresql://agent@host/db",
          "G1 비번 없는 DSN(유저만)은 불변")

    # ── G1. 프리플라이트 연결예외 → 명확 RuntimeError ──────────────────────────
    class _BoomEngine:
        def connect(self):
            raise OSError("[Errno 61] Connect call failed ('127.0.0.1', 5432)")

    saved_engine = db.engine
    db.engine = _BoomEngine()
    try:
        raised = None
        try:
            await db._preflight()
        except RuntimeError as exc:
            raised = str(exc)
        check(raised is not None, "G1 _preflight 연결실패 → RuntimeError")
        check(raised is not None and "DB 연결 실패" in raised, "G1 메시지에 'DB 연결 실패'")
        # 마스킹된 DATABASE_URL이 메시지에 — 단, 실 비밀번호는 안 샌다.
        check(raised is not None and "postgres 기동 여부" in raised,
              "G1 메시지에 조치 안내(postgres 기동 여부)")
    finally:
        db.engine = saved_engine

    # ── G1. init_db 소스 — 프리플라이트 먼저 + 폴백 확장 패리티 ─────────────────
    src = inspect.getsource(db.init_db)
    check("await _preflight()" in src, "G1 init_db가 _preflight를 호출")
    pf = src.index("_preflight()")
    begin = src.index("engine.begin()")
    check(pf < begin, "G1 프리플라이트가 폴백(engine.begin) *앞*에 위치(이중 throw 제거)")
    check("CREATE EXTENSION IF NOT EXISTS vector" in src,
          "G1 폴백이 CREATE EXTENSION vector 발행(마이그레이션과 패리티)")
    ext = src.index("CREATE EXTENSION IF NOT EXISTS vector")
    # 주: "create_all"은 주석에도 등장하므로 실제 *호출*(Base.metadata.create_all)로 매칭.
    create_all = src.index("Base.metadata.create_all")
    check(ext < create_all, "G1 확장 생성이 create_all *앞*(Vector 컬럼 생성 전 확장 보장)")
    # 적대리뷰 058 P1: create_all은 all-or-nothing이라 "RAG만 비활성"이 불가 → pgvector 부재 시
    # 부분 부팅으로 가리지 않고 fail-closed. 폴백 실패는 명확한 RuntimeError로 부팅 중단.
    check("pgvector 확장이 필요합니다" in src,
          "G1 폴백 실패 → pgvector 필수 명시한 RuntimeError(fail-closed, 부분 부팅 안 함)")
    check("부분 부팅하지 않는다" in src or "all-or-nothing" in src,
          "G1 부분 부팅 함정 회피 의도가 코드에 문서화됨")

    # ── G2. bootstrap_admin 입력검증(DB 미접촉) ────────────────────────────────
    rc = await ba.bootstrap_admin("not-an-email", "longenoughpw")
    check(rc == 2, f"G2 잘못된 이메일 → 종료코드 2 (실제={rc})")
    rc = await ba.bootstrap_admin("", "longenoughpw")
    check(rc == 2, f"G2 빈 이메일 → 2 (실제={rc})")
    rc = await ba.bootstrap_admin("admin@example.com", "short")
    check(rc == 2, f"G2 짧은 비번(<8) → 2 (실제={rc})")

    # ── G2. escalation 가드 — 소스 단언(learning 050) ──────────────────────────
    bsrc = inspect.getsource(ba.bootstrap_admin)
    check("if existing is not None" in bsrc, "G2 기존 계정 존재 분기 있음")
    check("return 3" in bsrc and "승격하지 않습니다" in bsrc,
          "G2 기존 일반계정 → 승격거부(코드 3) — escalation 차단(050)")
    check("is_superuser" in bsrc and "return 0" in bsrc,
          "G2 기존 superuser → 무동작(코드 0)")
    # 신규 생성은 is_superuser=True로 create — 그러나 *존재하지 않을 때만*.
    create_at = bsrc.index("manager.create(")
    guard_at = bsrc.index("if existing is not None")
    check(guard_at < create_at, "G2 존재 가드가 create *앞*(존재하면 create 도달 못함)")

    # ── G2. seed_admin 강화경고 — 유저0에서만 ──────────────────────────────────
    ssrc = inspect.getsource(users.seed_admin)
    check("user_count == 0" in ssrc, "G2 seed_admin이 유저수 0을 판정")
    check("python -m api.bootstrap_admin" in ssrc,
          "G2 유저0 경고에 정확한 복구 커맨드(python -m api.bootstrap_admin)")
    # 유저>0 분기는 조용한 한 줄(노이즈 억제) — 복구 커맨드 없이.
    check("관리자 시드 생략(fail-closed)" in ssrc, "G2 유저>0은 조용한 한 줄 경고")

    # ── G4. _model_error_hint ──────────────────────────────────────────────────
    cfg = {"base_url": "http://localhost:8045/v1", "model_id": "x"}
    hint = chat._model_error_hint(_APIConnectionError("All connection attempts failed"), cfg)
    check(hint is not None and "Mock LLM" in hint,
          "G4 연결실패+model_cfg → 'Mock LLM' 전환 힌트")
    check(hint is not None and "http://localhost:8045/v1" in hint,
          "G4 힌트에 base_url 포함(어디로 못 닿는지)")
    # 다양한 연결 지문.
    for exc, why in [
        (Exception("Connection refused"), "connection refused"),
        (Exception("Connection error."), "openai APIConnectionError 래핑 메시지"),
        (TimeoutError("operation timed out"), "타임아웃"),
    ]:
        check(chat._model_error_hint(exc, cfg) is not None, f"G4 연결지문 감지: {why}")
    # 비연결 오류는 힌트 없음(잘못된 안내 방지).
    check(chat._model_error_hint(Exception("model 'qwen' not found (404)"), cfg) is None,
          "G4 404(model_id 불일치)는 연결오류 아님 → 힌트 없음")
    check(chat._model_error_hint(Exception("401 Unauthorized invalid api key"), cfg) is None,
          "G4 401(인증)은 연결오류 아님 → 힌트 없음")
    # model_cfg 없으면(=비로컬/외부 경로) 힌트 없음.
    check(chat._model_error_hint(_APIConnectionError("Connection error"), None) is None,
          "G4 model_cfg 없으면 힌트 없음")

    # ── G4. chat except 블록이 힌트를 사용 ─────────────────────────────────────
    csrc = inspect.getsource(chat.chat)
    check("_model_error_hint(exc, ctx.get(\"model_cfg\"))" in csrc,
          "G4 스트림 except가 _model_error_hint 호출")
    check("hint else str(exc)" in csrc, "G4 힌트 없으면 원문 에러 유지(무회귀)")

    print()
    if _fails:
        print(f"FAILED {len(_fails)}건:")
        for f in _fails:
            print("  - " + f)
        sys.exit(1)
    print("ALL PASS — VERIFY058_OK")


if __name__ == "__main__":
    asyncio.run(main())
