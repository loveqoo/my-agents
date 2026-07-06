#!/usr/bin/env python3
"""노코드 가이드 md → 어드민 정적 HTML 빌드.

    python3 docs/guide/build-html.py

- 입력: docs/guide/nocode-agent-guide.md (+ images/guide-*.png)
- 출력: admin/public/guide/index.html + admin/public/guide/images/*.png
  (vite가 public/을 루트로 서빙 → 어드민 "가이드" 메뉴가 /guide/index.html을 새 탭으로 연다)
- 가이드 본문·스크린샷을 갱신하면 이 스크립트를 다시 돌린다
  (스크린샷 갱신은 tests/browser/shot-guide-menus.mjs).
"""
import html
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "docs/guide/nocode-agent-guide.md")
IMG_SRC = os.path.join(ROOT, "docs/guide/images")
OUT_DIR = os.path.join(ROOT, "admin/public/guide")

LI_RE = re.compile(r"^\s*- ")


def inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', s)
    return s


def convert(src: str) -> str:
    lines = src.split("\n")
    out: list[str] = []
    para: list[str] = []
    i = 0
    in_list: str | bool = False  # False | True(ul) | "ol"
    in_bq = False

    def flush_para():
        nonlocal para
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para = []

    def close_blocks():
        nonlocal in_list, in_bq
        if in_list == "ol":
            out.append("</ol>")
        elif in_list:
            out.append("</ul>")
        in_list = False
        if in_bq:
            out.append("</blockquote>")
            in_bq = False

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        m_img = re.match(r"^!\[(.*?)\]\((.*?)\)\s*$", s)
        if m_img:
            flush_para()
            close_blocks()
            alt, path = m_img.group(1), m_img.group(2)
            out.append(
                f'<figure><img src="{html.escape(path)}" alt="{html.escape(alt)}">'
                f"<figcaption>{html.escape(alt)}</figcaption></figure>"
            )
            i += 1
            continue
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:\-|]+\|?$", lines[i + 1].strip()):
            flush_para()
            close_blocks()
            hdr = [c.strip() for c in ln.strip().strip("|").split("|")]
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(h)}</th>" for h in hdr) + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue
        if s.startswith("### "):
            flush_para(); close_blocks(); out.append(f"<h3>{inline(s[4:])}</h3>")
        elif s.startswith("## "):
            flush_para(); close_blocks(); out.append(f"<h2>{inline(s[3:])}</h2>")
        elif s.startswith("# "):
            flush_para(); close_blocks(); out.append(f"<h1>{inline(s[2:])}</h1>")
        elif s.startswith("> "):
            flush_para()
            if in_list:
                out.append("</ol>" if in_list == "ol" else "</ul>")
                in_list = False
            if not in_bq:
                out.append("<blockquote>")
                in_bq = True
            out.append("<p>" + inline(s[2:]) + "</p>")
        elif re.match(r"^\d+\. ", s):
            flush_para()
            if in_bq:
                out.append("</blockquote>"); in_bq = False
            if in_list is True:
                out.append("</ul>"); in_list = False
            if not in_list:
                out.append("<ol>"); in_list = "ol"
            out.append("<li>" + inline(re.sub(r"^\d+\. ", "", s)) + "</li>")
        elif LI_RE.match(ln):
            flush_para()
            if in_bq:
                out.append("</blockquote>"); in_bq = False
            if in_list == "ol":
                out.append("</ol>"); in_list = False
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append("<li>" + inline(LI_RE.sub("", ln)) + "</li>")
        elif s == "---":
            flush_para(); close_blocks(); out.append("<hr>")
        elif s == "":
            flush_para(); close_blocks()
        else:
            if in_bq:
                out.append("<p>" + inline(s) + "</p>")
            else:
                para.append(s)
        i += 1
    flush_para()
    close_blocks()
    return "\n".join(out)


def main() -> None:
    body = convert(open(SRC, encoding="utf-8").read())
    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>노코드 에이전트 만들기 가이드</title>
<style>
body{{font-family:-apple-system,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;max-width:860px;margin:0 auto;padding:32px 20px;line-height:1.7;color:#222}}
h1{{border-bottom:2px solid #eee;padding-bottom:8px}} h2{{margin-top:2em;border-bottom:1px solid #eee;padding-bottom:6px}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{border:1px solid #ddd;padding:6px 10px;text-align:left}}
th{{background:#f7f7f7}} blockquote{{border-left:4px solid #4a90d9;background:#f4f8fc;margin:12px 0;padding:8px 16px;border-radius:0 6px 6px 0}}
code{{background:#f2f2f2;padding:1px 5px;border-radius:4px;font-size:.9em}}
figure{{margin:16px 0;text-align:center}} figure img{{max-width:100%;border:1px solid #ddd;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
figcaption{{color:#888;font-size:13px;margin-top:4px}}
</style>
</head>
<body>
{body}
</body>
</html>
"""
    os.makedirs(os.path.join(OUT_DIR, "images"), exist_ok=True)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    copied = 0
    for name in sorted(os.listdir(IMG_SRC)):
        if name.endswith(".png"):
            shutil.copy2(os.path.join(IMG_SRC, name), os.path.join(OUT_DIR, "images", name))
            copied += 1
    # 참조 무결성: html의 이미지 참조가 전부 복사됐는지 측정(자가선언 금지)
    refs = re.findall(r'src="(images/[\w.-]+)"', page)
    missing = [r for r in refs if not os.path.exists(os.path.join(OUT_DIR, r))]
    print(f"WROTE {OUT_DIR}/index.html ({os.path.getsize(os.path.join(OUT_DIR, 'index.html')) // 1024}KB)")
    print(f"IMAGES copied={copied} refs={len(refs)} missing={missing or '없음'}")


if __name__ == "__main__":
    main()
