"""스펙 363 검증 보조 — admin 유저 스코프에 회상 쿼리와 동일 텍스트 기억 1건 verbatim 시드.

단순 에이전트가 유저 장기(user_id 축)로 회상하므로(스샷의 "유저 장기"), 브라우저 테스트가 이 텍스트를
그대로 물으면 mock 결정 임베딩(정확 텍스트 일치)으로 확실히 회상된다.

용법:
  seed  <email> <text>   → 적재(멱등 아님 — 중복 add 무해, verbatim)
  clear <email> <text>   → 그 텍스트와 일치하는 회상 기억 삭제(정리)
"""

import asyncio
import sys

sys.path.insert(0, "packages/api/src")

from sqlalchemy import select  # noqa: E402

from api import memory as memory_mod  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.mem_config import default_mem_cfg  # noqa: E402
from api.models import User  # noqa: E402


async def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    action, email, text = sys.argv[1], sys.argv[2], sys.argv[3]
    async with SessionLocal() as s:
        u = await s.scalar(select(User).where(User.email == email))
        if not u:
            raise SystemExit(f"유저 없음: {email}")
        uid = str(u.id)
        mem_cfg = await default_mem_cfg(s)
    if mem_cfg is None:
        raise SystemExit("mem_cfg 미해석 — 메모리 비활성")
    if action == "seed":
        memory_mod.add({"user_id": uid}, [{"role": "user", "content": text}], mem_cfg, False)
        hits = memory_mod.search({"user_id": uid}, text, mem_cfg)
        print(f"SEEDED uid={uid} · 회상확인 {len(hits)}건")
    elif action == "clear":
        # search 결과엔 id가 없다({text,score,scope}) → list_memories로 id를 얻어 텍스트 일치분만 삭제.
        rows = memory_mod.list_memories({"user_id": uid}, mem_cfg)
        removed = 0
        for r in rows:
            body = (r.get("memory") or r.get("text") or "") if isinstance(r, dict) else ""
            mid = r.get("id") if isinstance(r, dict) else None
            if text in body and mid and memory_mod.delete_memory(mid, mem_cfg):
                removed += 1
        print(f"CLEARED uid={uid} · 삭제 {removed}건")
    else:
        raise SystemExit("action은 seed|clear")


if __name__ == "__main__":
    asyncio.run(main())
