#!/usr/bin/env python3
"""가이드 md → 어드민 정적 HTML 빌드(노코드+개발자 2종).

    python3 docs/guide/build-html.py

- 입력: docs/guide/nocode-agent-guide.md · artifact-agent-developer.md (+ images/guide-*.png)
- 출력: admin/public/guide/{index.html, developer.html} + images/*.png
  (vite가 public/을 루트로 서빙 → 어드민 "가이드" 메뉴가 /guide/index.html을 새 탭으로 연다)
- 링크 규칙: 가이드 상호 .md 링크는 대응 html로 재작성, 그 외 .md 링크(스펙 등 저장소 전용)는
  깨진 href를 남기지 않도록 **텍스트로 강등**한다.
- 갱신: 본문 수정 후 이 스크립트 재실행(스크린샷 갱신은 tests/browser/shot-guide-menus.mjs).
"""
import html
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUIDE_DIR = os.path.join(ROOT, "docs/guide")
IMG_SRC = os.path.join(GUIDE_DIR, "images")
OUT_DIR = os.path.join(ROOT, "admin/public/guide")

#: md 파일 → (출력 html, 페이지 타이틀, 내비 라벨)
PAGES = {
    "nocode-agent-guide.md": ("index.html", "노코드 에이전트 만들기 가이드", "노코드 가이드"),
    "artifact-agent-developer.md": ("developer.html", "산출물형 에이전트 저작 가이드 (개발자용)", "개발자 가이드"),
}
MD_TO_HTML = {md: out for md, (out, _, _) in PAGES.items()}

LI_RE = re.compile(r"^\s*- ")


def rewrite_link(m: re.Match) -> str:
    """[텍스트](url) — 가이드 md는 html로, 그 외 .md는 텍스트 강등, 나머지는 그대로."""
    text, url = m.group(1), m.group(2)
    base = os.path.basename(url)
    if base in MD_TO_HTML:
        return f'<a href="{MD_TO_HTML[base]}">{text}</a>'
    if url.endswith(".md"):
        return text  # 저장소 전용 링크(스펙 등) — 서빙 컨텍스트에서 404이므로 텍스트로
    return f'<a href="{html.escape(url)}">{text}</a>'


def inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", rewrite_link, s)
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
        # 펜스 코드블록(```lang … ```) — 이스케이프만 하고 그대로 <pre>에 담는다.
        if s.startswith("```"):
            flush_para()
            close_blocks()
            lang = s[3:].strip()
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # 닫는 ``` 스킵
            cls = f' class="lang-{html.escape(lang)}"' if lang else ""
            out.append(f"<pre{cls}><code>" + html.escape("\n".join(code)) + "</code></pre>")
            continue
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


def nav_html(current_out: str) -> str:
    links = []
    for _md, (out_name, _title, label) in PAGES.items():
        if out_name == current_out:
            links.append(f'<span class="cur">{label}</span>')
        else:
            links.append(f'<a href="{out_name}">{label}</a>')
    return '<nav class="guide-nav">' + " · ".join(links) + "</nav>"


def render_page(md_name: str) -> str:
    out_name, title, _label = PAGES[md_name]
    body = convert(open(os.path.join(GUIDE_DIR, md_name), encoding="utf-8").read())
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{font-family:-apple-system,'Apple SD Gothic Neo','Noto Sans KR',sans-serif;max-width:860px;margin:0 auto;padding:32px 20px;line-height:1.7;color:#222}}
h1{{border-bottom:2px solid #eee;padding-bottom:8px}} h2{{margin-top:2em;border-bottom:1px solid #eee;padding-bottom:6px}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{border:1px solid #ddd;padding:6px 10px;text-align:left}}
th{{background:#f7f7f7}} blockquote{{border-left:4px solid #4a90d9;background:#f4f8fc;margin:12px 0;padding:8px 16px;border-radius:0 6px 6px 0}}
code{{background:#f2f2f2;padding:1px 5px;border-radius:4px;font-size:.9em}}
pre{{background:#1f2430;color:#e6e6e6;padding:14px 16px;border-radius:8px;overflow-x:auto;font-size:13px;line-height:1.55}}
pre code{{background:none;padding:0;color:inherit}}
figure{{margin:16px 0;text-align:center}} figure img{{max-width:100%;border:1px solid #ddd;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
figcaption{{color:#888;font-size:13px;margin-top:4px}}
.guide-nav{{margin-bottom:20px;padding:8px 14px;background:#f7f7f7;border-radius:8px;font-size:14px}}
.guide-nav .cur{{font-weight:700}}
</style>
</head>
<body>
{nav_html(out_name)}
{body}
</body>
</html>
"""


def main() -> None:
    os.makedirs(os.path.join(OUT_DIR, "images"), exist_ok=True)
    all_refs: list[tuple[str, str]] = []
    for md_name, (out_name, _t, _l) in PAGES.items():
        page = render_page(md_name)
        path = os.path.join(OUT_DIR, out_name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
        for r in re.findall(r'src="(images/[\w.-]+)"', page):
            all_refs.append((out_name, r))
        # 페이지 간 링크도 무결성 대상
        for a in re.findall(r'href="([\w.-]+\.html)"', page):
            all_refs.append((out_name, a))
        print(f"WROTE {path} ({os.path.getsize(path) // 1024}KB)")
    copied = 0
    for name in sorted(os.listdir(IMG_SRC)):
        if name.endswith(".png"):
            shutil.copy2(os.path.join(IMG_SRC, name), os.path.join(OUT_DIR, "images", name))
            copied += 1
    missing = [f"{page}→{ref}" for page, ref in all_refs if not os.path.exists(os.path.join(OUT_DIR, ref))]
    # 잔존 .md href는 0이어야(전부 재작성/강등) — 측정으로 확인
    leftover_md = []
    for _md, (out_name, _t, _l) in PAGES.items():
        content = open(os.path.join(OUT_DIR, out_name), encoding="utf-8").read()
        leftover_md += [f"{out_name}:{m}" for m in re.findall(r'href="[^"]+\.md"', content)]
    print(f"IMAGES copied={copied} | refs={len(all_refs)} missing={missing or '없음'} | md-href 잔존={leftover_md or '0'}")


if __name__ == "__main__":
    main()
