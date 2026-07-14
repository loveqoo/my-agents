"""INDEX 재압축 보존 불변식 — 압축은 **버리는 게 아니라 줄이는 것**이다(자가선언 금지, 측정으로).

재압축이 정보를 잃지 않았음을 대조로 증명한다:
  I1 항목 하나도 안 빠졌다 — NNN 번호 집합이 before == after.
  I2 recall 앵커 보존 — 각 항목의 `[키워드]` 블록이 있었으면 after에도 있고, before 키워드가
     after의 부분집합(줄여도 키워드는 안 버린다).
  I3 압축이 실제로 일어났다 — 200자 초과 줄 수가 유의미하게 줄었다.

실행: uv run python tests/verify_index_recompress.py <before.json>
  (before.json은 재압축 **전에** 이 스크립트의 snapshot 모드로 찍는다.)
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDEXES = {
    "spec": ROOT / "docs/spec/INDEX.md",
    "retrospect": ROOT / ".dev/retrospect/INDEX.md",
    "learning": ROOT / ".dev/learning/INDEX.md",
}
_ITEM = re.compile(r"^- (\d{3})\b")
_KW = re.compile(r"\[([^\]]*)\]")


def parse(path: pathlib.Path) -> dict[str, dict]:
    """NNN → {len, keywords[]}. 항목이 아닌 줄은 무시."""
    out: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        m = _ITEM.match(line)
        if not m:
            continue
        nnn = m.group(1)
        # 키워드 블록 = 대괄호 안 쉼표 목록(마지막 [...]을 앵커로 — 후크 안 대괄호와 구분)
        kws: list[str] = []
        for grp in _KW.findall(line):
            if "," in grp or re.match(r"^[a-z0-9-]+$", grp.strip()):
                kws = [k.strip() for k in grp.split(",") if k.strip()]
        out[nnn] = {"len": len(line), "keywords": sorted(set(kws))}
    return out


def snapshot() -> None:
    snap = {name: parse(p) for name, p in INDEXES.items()}
    print(json.dumps(snap, ensure_ascii=False))


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "snapshot":
        snapshot()
        return
    before = json.loads(pathlib.Path(sys.argv[1]).read_text())
    fails: list[str] = []
    passed = 0

    def check(cond: object, msg: str) -> None:
        nonlocal passed
        print(("  ok  " if cond else " FAIL ") + msg)
        if cond:
            passed += 1
        else:
            fails.append(msg)

    for name, path in INDEXES.items():
        b = before[name]
        a = parse(path)
        # I1 항목 집합 동일
        lost = sorted(set(b) - set(a))
        added = sorted(set(a) - set(b))
        check(not lost, f"[{name}] I1 빠진 항목 0 (없어짐: {lost or '—'})")
        if added:
            print(f"  (참고) [{name}] 새 항목 {added} — before 이후 추가분, 무해")
        # I2 키워드 부분집합 보존
        dropped = {
            n: sorted(set(b[n]["keywords"]) - set(a[n]["keywords"]))
            for n in set(b) & set(a)
            if set(b[n]["keywords"]) - set(a[n]["keywords"])
        }
        check(not dropped, f"[{name}] I2 키워드 손실 0 (버려진 키워드: {dict(list(dropped.items())[:5]) or '—'})")
        # I3 압축 실효
        big_b = sum(1 for n in b if b[n]["len"] > 200)
        big_a = sum(1 for n in a if a[n]["len"] > 200)
        check(
            big_a < big_b,
            f"[{name}] I3 200자 초과 줄 {big_b} → {big_a} (실제 압축됨)",
        )

    print()
    if fails:
        print(f"FAIL {len(fails)}건: {fails}")
        sys.exit(1)
    print(f"VERIFY_INDEX_OK — {passed}건 전부 통과")


if __name__ == "__main__":
    main()
