"""스펙 035 검증 — Provider 엔티티(모델 연결처 분리).

인프로세스 httpx(ASGI) + 실 DB로 수치/불변식 단언. 검증용 provider·model을 고유
prefix(prov_v035_/mdl_v035_)로 삽입 → 단언 → **삭제**(자가정리, 실데이터 불간섭).

단언:
  1. /providers 셰이프 {id,name,protocol,base_url,api_key(마스킹),modelCount}.
  2. /models 셰이프: provider_id·provider_name·base_url 존재, **api_key 키 없음**(연결처는 provider 상속).
  3. 무결성: 모든 모델의 provider_id가 providers에 존재 + model.base_url == provider.base_url.
  4. 비밀 안전: provider api_key는 null 또는 마스킹(••)뿐 — 평문/암호문(gAAAAA) 비노출.
  5. modelCount: provider별 modelCount == 그 provider를 가리키는 모델 수, 합 == 전체 모델 수.
  6. CRUD 왕복 + RESTRICT: provider 생성 → 키 마스킹 → 그 아래 모델 생성 → provider 삭제 409(차단)
     → 모델 삭제 → provider 삭제 204. 마스킹 키로 수정 시 키 보존.
  7. 연결 테스트: 잘못된 base_url로 /providers/test → 예외 없이 ok=False.

실행: .venv/bin/python tests/verify_035_provider_entity.py
"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "api", "src"))

import httpx  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from api.auth import _token  # noqa: E402
from api.crypto import SECRET_MASK  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import ModelConfig, Provider  # noqa: E402

_AUTH = {"Authorization": f"Bearer {_token()}"}
_fails: list[str] = []
PP = "prov_v035_"
MP = "mdl_v035_"


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _secret_safe(v) -> bool:
    """비밀 출력이 안전한가 — null 또는 마스킹만 허용, 평문/암호문 금지."""
    if v is None:
        return True
    if v == SECRET_MASK:
        return True
    return False  # 그 외(평문·gAAAAA 암호문)는 누출


async def _cleanup() -> None:
    async with SessionLocal() as s:
        await s.execute(delete(ModelConfig).where(ModelConfig.name.like(f"{MP}%")))
        await s.execute(delete(Provider).where(Provider.name.like(f"{PP}%")))
        await s.commit()


async def main() -> None:
    await _cleanup()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t", headers=_AUTH) as c:
            # --- 셰이프 ---
            print("[shape] /providers · /models")
            provs = (await c.get("/providers")).json()
            mods = (await c.get("/models")).json()
            check(isinstance(provs, list) and isinstance(mods, list), "둘 다 리스트")
            if provs:
                p0 = provs[0]
                check(set(p0) >= {"id", "name", "protocol", "base_url", "api_key", "modelCount"},
                      f"provider 키 집합 (got {sorted(p0)})")
            if mods:
                m0 = mods[0]
                check({"provider_id", "provider_name", "base_url"} <= set(m0),
                      "model에 provider_id·provider_name·base_url 존재")
                check("api_key" not in m0, "model에 api_key 키 없음(연결처는 provider 상속)")

            # --- 무결성: 모델→provider 참조 + base_url 일치 ---
            print("[integrity] 모델 provider 참조")
            pmap = {p["id"]: p for p in provs}
            orphan = [m["name"] for m in mods if m["provider_id"] not in pmap]
            check(not orphan, f"고아 모델 없음 (orphan={orphan})")
            mism = [m["name"] for m in mods
                    if m["provider_id"] in pmap and m["base_url"] != pmap[m["provider_id"]]["base_url"]]
            check(not mism, f"model.base_url == provider.base_url (mismatch={mism})")
            namem = [m["name"] for m in mods
                     if m["provider_id"] in pmap and m["provider_name"] != pmap[m["provider_id"]]["name"]]
            check(not namem, f"model.provider_name == provider.name (mismatch={namem})")

            # --- 비밀 안전 ---
            print("[secret] provider api_key 마스킹")
            leaked = [p["name"] for p in provs if not _secret_safe(p["api_key"])]
            check(not leaked, f"평문/암호문 비노출 (leaked={leaked})")

            # --- modelCount ---
            print("[count] provider.modelCount 정합")
            from collections import Counter
            actual = Counter(m["provider_id"] for m in mods)
            bad = [p["name"] for p in provs if p["modelCount"] != actual.get(p["id"], 0)]
            check(not bad, f"각 provider modelCount 정확 (bad={bad})")
            check(sum(p["modelCount"] for p in provs) == len(mods), "modelCount 합 == 전체 모델 수")

            # --- CRUD 왕복 + RESTRICT ---
            print("[crud] provider 생성→모델→삭제 RESTRICT")
            pc = (await c.post("/providers", json={
                "name": f"{PP}a", "protocol": "openai-compatible",
                "base_url": "http://127.0.0.1:65535/v1", "api_key": "sk-test-123",
            }))
            check(pc.status_code == 201, f"provider 생성 201 (got {pc.status_code})")
            pid = pc.json()["id"]
            check(_secret_safe(pc.json()["api_key"]) and pc.json()["api_key"] == SECRET_MASK,
                  "생성 직후 키 마스킹")
            check(pc.json()["modelCount"] == 0, "신규 provider modelCount 0")

            # 마스킹 키로 수정 → 키 보존(DB에서 복호화로 확인)
            await c.put(f"/providers/{pid}", json={
                "name": f"{PP}a2", "protocol": "openai-compatible",
                "base_url": "http://127.0.0.1:65535/v1", "api_key": SECRET_MASK,
            })
            async with SessionLocal() as s:
                from api import crypto
                p_db = await s.get(Provider, __import__("uuid").UUID(pid))
                check(crypto.decrypt(p_db.api_key) == "sk-test-123", "마스킹 수정 시 기존 키 보존")

            # 그 아래 모델 생성
            mc = (await c.post("/models", json={
                "name": f"{MP}a", "provider_id": pid, "model_id": "x", "kind": "chat",
                "is_default": False, "params": {},
            }))
            check(mc.status_code == 201, f"모델 생성 201 (got {mc.status_code})")
            mid = mc.json()["id"]
            check(mc.json()["provider_id"] == pid and mc.json()["base_url"] == "http://127.0.0.1:65535/v1",
                  "모델이 provider base_url 상속")
            # provider modelCount 1로 증가
            pget = (await c.get(f"/providers/{pid}")).json()
            check(pget["modelCount"] == 1, "모델 매달린 후 modelCount 1")

            # provider 삭제 → 409(RESTRICT)
            d1 = await c.delete(f"/providers/{pid}")
            check(d1.status_code == 409, f"매달린 모델 있으면 provider 삭제 409 (got {d1.status_code})")
            # 모델 삭제 후 provider 삭제 204
            check((await c.delete(f"/models/{mid}")).status_code == 204, "모델 삭제 204")
            check((await c.delete(f"/providers/{pid}")).status_code == 204, "모델 제거 후 provider 삭제 204")

            # --- 연결 테스트(예외 없이 실패 보고) ---
            print("[probe] 잘못된 base_url 테스트")
            t = (await c.post("/providers/test", json={"base_url": "http://127.0.0.1:65535/v1"})).json()
            check(t["ok"] is False and t["reachable"] is False, "도달 불가 → ok=False·reachable=False")
    finally:
        await _cleanup()


if __name__ == "__main__":
    asyncio.run(main())
    print()
    if _fails:
        print(f"❌ {len(_fails)} FAILED")
        for f in _fails:
            print("   - " + f)
        sys.exit(1)
    print("✅ ALL PASS")
