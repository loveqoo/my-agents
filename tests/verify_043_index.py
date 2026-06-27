#!/usr/bin/env python3
"""스펙 043 검증 — 자산 인덱스 정합성 자가검증.

확인 항목:
  (a) 각 INDEX.md 의 항목 줄 수 == 실제 파일 수
  (b) 모든 NNN 이 인덱스에 정확히 1회 등장(파일↔인덱스 일대일)
  (c) [archived] 표시 항목은 docs/spec/archive/ 에 실존
  (d) 아카이브 이동 후 깨진 `docs/spec/NNN`(archive 미경유) 상호참조 0건

재사용: 새 자산 추가 후 인덱스 갱신 누락을 사후 탐지하는 회귀 검사로도 쓴다.
실행: python3 tests/verify_043_index.py  (저장소 루트에서)
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))

# (디렉터리, 인덱스경로, 추가 하위디렉터리[아카이브])
TARGETS = [
    (os.path.join(ROOT, ".dev/learning"), os.path.join(ROOT, ".dev/learning/INDEX.md"), None),
    (os.path.join(ROOT, ".dev/retrospect"), os.path.join(ROOT, ".dev/retrospect/INDEX.md"), None),
    (os.path.join(ROOT, "docs/spec"), os.path.join(ROOT, "docs/spec/INDEX.md"),
     os.path.join(ROOT, "docs/spec/archive")),
]

NNN_FILE = re.compile(r"^(\d{3})-.*\.md$")
NNN_LINE = re.compile(r"^- (\d{3}) ")

failures = []
def check(cond, msg):
    if not cond:
        failures.append(msg)


def nnn_files_in(d):
    out = {}
    if not os.path.isdir(d):
        return out
    for fn in os.listdir(d):
        m = NNN_FILE.match(fn)
        if m:
            out[m.group(1)] = fn
    return out


for d, index_path, archive in TARGETS:
    label = os.path.relpath(d, ROOT)
    check(os.path.isfile(index_path), f"[{label}] INDEX.md 없음")
    if not os.path.isfile(index_path):
        continue

    files = nnn_files_in(d)
    if archive:
        files.update(nnn_files_in(archive))  # 같은 번호공간(겹침 없음 가정)

    with open(index_path, encoding="utf-8") as f:
        lines = f.readlines()
    entry_nnns = [NNN_LINE.match(ln).group(1) for ln in lines if NNN_LINE.match(ln)]

    # (a) 줄 수 == 파일 수
    check(len(entry_nnns) == len(files),
          f"[{label}] 인덱스 항목 {len(entry_nnns)}개 != 실제 파일 {len(files)}개")

    # (b) 일대일 (중복 없음, 양방향 일치)
    dup = {n for n in entry_nnns if entry_nnns.count(n) > 1}
    check(not dup, f"[{label}] 인덱스 중복 NNN: {sorted(dup)}")
    missing = set(files) - set(entry_nnns)
    extra = set(entry_nnns) - set(files)
    check(not missing, f"[{label}] 파일은 있는데 인덱스에 없음: {sorted(missing)}")
    check(not extra, f"[{label}] 인덱스에 있는데 파일 없음: {sorted(extra)}")

    # (c) [archived] 항목은 archive/ 에 실존
    if archive:
        arch_nnns = set(nnn_files_in(archive))
        for ln in lines:
            m = NNN_LINE.match(ln)
            if not m:
                continue
            tagged = "[archived]" in ln
            n = m.group(1)
            if tagged:
                check(n in arch_nnns, f"[{label}] {n} [archived] 표시인데 archive/ 에 없음")
            else:
                check(n not in arch_nnns, f"[{label}] {n} archive/ 에 있는데 [archived] 미표시")

# (d) 깨진 archive 미경유 상호참조 — 034~042 를 archive/ 없이 docs/spec/ 직접 참조
broken = []
ref = re.compile(r"docs/spec/(03[4-9]|04[0-2])-")
for dirpath, dirnames, filenames in os.walk(ROOT):
    if any(skip in dirpath for skip in (".git", "node_modules", "__pycache__", "/dist", "/.venv")):
        continue
    for fn in filenames:
        if not (fn.endswith(".md") or fn.endswith(".py")):
            continue
        p = os.path.join(dirpath, fn)
        try:
            with open(p, encoding="utf-8") as f:
                for i, ln in enumerate(f, 1):
                    if ref.search(ln) and "docs/spec/archive/" not in ln:
                        broken.append(f"{os.path.relpath(p, ROOT)}:{i}")
        except (UnicodeDecodeError, OSError):
            continue
check(not broken, f"[refs] 깨진(archive 미경유) 034~042 참조: {broken}")

# (e) archive/ 파일의 *나가는* 상대경로 .md 링크가 실제 resolve 되는가
#     (L3 아카이브 이동은 들어오는 참조뿐 아니라 옮겨진 파일이 내보내는 링크도 깬다.)
archive_dir = os.path.join(ROOT, "docs/spec/archive")
out_link = re.compile(r"\]\((\.{0,2}/?[^)]*?\d{3}-[^)]*?\.md)\)")
dangling = []
if os.path.isdir(archive_dir):
    for fn in os.listdir(archive_dir):
        if not fn.endswith(".md"):
            continue
        p = os.path.join(archive_dir, fn)
        with open(p, encoding="utf-8") as f:
            text = f.read()
        for target in out_link.findall(text):
            resolved = os.path.normpath(os.path.join(archive_dir, target))
            if not os.path.isfile(resolved):
                dangling.append(f"{fn} -> {target}")
check(not dangling, f"[refs] archive 나가는 상대링크 깨짐: {dangling}")

if failures:
    print("FAIL")
    for m in failures:
        print("  -", m)
    sys.exit(1)
print("PASS — 인덱스 3종 정합(줄수=파일수, 일대일, archived 일치, 깨진 참조 0)")
