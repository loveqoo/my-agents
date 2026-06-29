"""스펙 062 라이브 통합 — POST /collections 에러가 `detail`을 담는지 실측 (통합 rung).

실행 중인 API(127.0.0.1:8000)+실 DB에 머신 Bearer로 붙어, 백엔드가 *큐레이션된 안전 사유*를
`detail`에 실제로 내려보내는지 확인한다. (프런트 D1은 이 `detail`을 그대로 노출 — verify_062_http_error.mjs가
추출 로직을, 이 테스트가 *백엔드가 정말 detail을 준다*는 글루를 검증. 메모리 verification-ladder.)

검증:
  L1  중복 이름 POST /collections → 409 + detail "같은 이름의 컬렉션이 이미 있습니다." (D1이 노출할 사유)
  L2  detail이 안전 문자열(토큰/스택/payload 미포함) — 백엔드 불변식 실측
  L3  (가능 시) 차원 불일치 모델로 생성 → 409 detail에 조치 문구 — 4096 모델 없으면 SKIP

실행: `.venv/bin/python tests/verify_062_live.py` (API가 127.0.0.1:8000에서 떠 있어야 함)
"""

import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

BASE = "http://127.0.0.1:8000"
TOK = os.environ["API_AUTH_TOKEN"]
AUTH = {"Authorization": f"Bearer {TOK}"}

_fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _req(method, path, *, headers=None, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# 기존 컬렉션 하나를 골라 그 이름으로 재생성 → 중복 409 유도 (임베딩 모델 id도 재사용).
status, raw = _req("GET", "/collections", headers=AUTH)
assert status == 200, f"GET /collections {status}: {raw[:200]}"
cols = json.loads(raw)
assert cols, "기존 컬렉션이 하나도 없어 중복-이름 시나리오를 만들 수 없음(시드 필요)"
victim = cols[0]
print(f"대상 컬렉션(중복 유도): name={victim['name']!r} model={victim['embedding_model_id']}")

# L1 — 중복 이름 생성 시도
status, raw = _req(
    "POST",
    "/collections",
    headers=AUTH,
    body={
        "name": victim["name"],
        "description": "verify_062 duplicate probe",
        "embedding_model_id": victim["embedding_model_id"],
    },
)
body = json.loads(raw) if raw.strip().startswith("{") else {}
detail = body.get("detail")
check(status == 409, f"L1 중복 이름 → 409 (실제 {status})")
check(isinstance(detail, str) and "이미" in detail, f"L1 detail에 중복 사유 포함: {detail!r}")

# L2 — detail 안전 문자열 불변식: 민감/내부 토큰 미포함
leak_markers = ["Bearer", "Traceback", "Authorization", TOK[:8], "/Users/", "secret"]
hit = [m for m in leak_markers if isinstance(detail, str) and m and m in detail]
check(not hit, f"L2 detail에 민감/내부 토큰 미노출 (누출 후보: {hit})")

# L3 — 차원 불일치 경로(가능 시): 모든 임베딩 모델을 훑어 4096 등 비-1024 후보로 생성 시도.
#       후보가 없으면 SKIP(브라우저 E2E·단위가 가시화 경로를 별도 입증).
status, raw = _req("GET", "/models", headers=AUTH)
mismatch_tried = False
if status == 200:
    models = json.loads(raw)
    emb = [m for m in models if m.get("kind") == "embedding"]
    # 이미 1024로 쓰이는 모델은 제외 — 새로운 차원을 가진 후보만 시도
    used = {c["embedding_model_id"] for c in cols}
    cand = [m for m in emb if m["id"] not in used]
    for m in cand:
        s2, r2 = _req(
            "POST",
            "/collections",
            headers=AUTH,
            body={
                "name": "verify062_dim_probe",
                "description": "dim mismatch probe",
                "embedding_model_id": m["id"],
            },
        )
        b2 = json.loads(r2) if r2.strip().startswith("{") else {}
        d2 = b2.get("detail", "")
        if s2 == 409 and isinstance(d2, str) and "차원" in d2:
            mismatch_tried = True
            check("선택하거나" in d2 or "요청하세요" in d2, f"L3 차원 불일치 detail에 조치 문구 포함: {d2!r}")
            break
        if s2 == 201:
            # 우연히 생성됨(1024 호환) — 정리하고 계속
            cid = b2.get("id")
            if cid:
                _req("DELETE", f"/collections/{cid}", headers=AUTH)
if not mismatch_tried:
    print("  skip  L3 차원 불일치 — 비-1024 임베딩 모델 후보 없음(단위·브라우저가 가시화 입증)")

print()
if _fails:
    print(f"062 live: {len(_fails)} FAIL")
    for f in _fails:
        print("  -", f)
    raise SystemExit(1)
print("062 live: PASS")
