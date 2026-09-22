#!/usr/bin/env python3
"""OpenX 本地交付工具。只读源文章；指定 --output 时仅创建新文件。"""
import argparse
import csv
import html
import io
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, unquote

import openx_audit as audit

WORK_HEADING = re.compile(r"^#{1,6}\s+(?:上稿用\s*SEO|内链清单|內鏈清單|发布前自检|發布前自檢|写作前确认|寫作前確認)", re.M)
WIKI = re.compile(r"(?<![!\\])\[\[([^\]\n]+)\]\]")


def public_body(body):
    """保留正文/FAQ/来源；截去交付工作区，排除代码与注释中的伪链接。"""
    visible = mask_code(body)
    m = WORK_HEADING.search(visible)
    bold_work = re.search(r"^\*\*(?:写作前确认|寫作前確認)\*\*", visible, re.M)
    ends = [x.start() for x in (m, bold_work) if x]
    return body[:min(ends)] if ends else body


def mask_code(body):
    """遮罩保持字符位置，供核验与导出共享，避免代码中的标题截断正文。"""
    blank = lambda s: re.sub(r"[^\n]", " ", s)
    body = re.sub(r"<!--.*?(?:-->|\Z)", lambda m: blank(m.group()), body, flags=re.S)
    lines, fence = [], None
    for line in body.splitlines(keepends=True):
        m = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            lines.append(blank(line))
            continue
        lines.append(blank(line) if fence or line.startswith(("    ", "\t")) else line)
    return re.sub(r"(`+).*?\1", lambda m: blank(m.group()), "".join(lines))


def prose(body):
    return mask_code(public_body(body))


def valid_url(value):
    value = str(value or "")
    try:
        u = urlsplit(value)
        _ = u.port  # 非数字或越界端口抛 ValueError。
        return (u.scheme == "https" and bool(u.hostname) and not u.username
                and not u.password and not re.search(r"[\x00-\x20\x7f\s<>\[\]()\\]", value)
                and u.hostname not in {"example.com", "example.org", "localhost", "..."})
    except ValueError:
        return False


def wiki_target(raw, lang):
    target = raw.split("|", 1)[0].split("#", 1)[0]
    path = Path(unquote(target))
    # 不可抹掉显式目录，尤其不能把繁中路径悄悄换成英文版本。
    if path.parent.as_posix() not in (".", lang, "03-文章/" + lang, "../" + lang):
        return ""
    return path.stem


def has_link(body, target):
    fm, _body, path = target
    visible = prose(body)
    names = {fm["article_id"], Path(path).stem}
    if any(wiki_target(m.group(1), fm["lang"]) in names for m in WIKI.finditer(visible)):
        return True
    url = str(fm.get("url") or "")
    return bool(url and any(link.split("#", 1)[0] == url.split("#", 1)[0]
                           for link in re.findall(r"(?<![!\\])\[[^\]\n]+\]\(([^\s)]+)\)", visible)))


def matrix_rows(text):
    """支持已落实明细与已勾销待补表；按表头而非固定列号识别。"""
    headers = None
    for n, line in enumerate(text.splitlines(), 1):
        if not line.lstrip().startswith("|"):
            headers = None
            continue
        cells = [x.strip() for x in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if any(c in cells for c in ("从（article_id）", "需修改的旧文", "需修改的文")):
            headers = cells
            continue
        if not headers or len(cells) != len(headers) or all(re.fullmatch(r"[-: ]*", c) for c in cells):
            continue
        row = dict(zip(headers, cells))
        done = row.get("状态") == "已落实" or bool(re.search(r"✅|\[x\]|已完成|已落实", row.get("完成", ""), re.I))
        if not done:
            continue
        source = next((row[k] for k in ("从（article_id）", "需修改的旧文", "需修改的文") if k in row), "")
        target = row.get("到（article_id）", row.get("链向", ""))
        src, dst = re.search(r"\bOX-\d+\b", source), re.search(r"\bOX-\d+\b", target)
        yield n, src.group() if src else "", dst.group() if dst else "", row.get("lang", row.get("语言", ""))


def link_issues(articles, matrix, lang=""):
    """返回问题列表；无语言的历史矩阵行只核源语言，不误判未建译文。"""
    index = defaultdict(list)
    for a in articles:
        index[(a[0].get("article_id"), a[0].get("lang"))].append(a)
    issues = []
    for n, src, dst, row_lang in matrix_rows(matrix):
        label = f"内链矩阵:{n} {src or '?'} → {dst or '?'}"
        if not src or not dst:
            issues.append(label + "：完成行缺有效文章 ID")
            continue
        sources = [a for a in articles if a[0].get("article_id") == src and
                   (a[0].get("lang") == row_lang if row_lang else
                    a[0].get("lang") == a[0].get("source_lang", "zh-Hant"))]
        if lang:
            sources = [a for a in sources if a[0].get("lang") == lang]
            if not sources:
                if row_lang and row_lang != lang:
                    continue
                if not row_lang and any(a[0].get("article_id") == src and a[0].get("source_lang", "zh-Hant") != lang for a in articles):
                    continue
        if not sources:
            issues.append(label + "：源文章/对应语言不存在")
        for source in sources:
            lg = source[0].get("lang")
            targets = index.get((dst, lg), [])
            if len(index[(src, lg)]) != 1 or len(targets) != 1:
                issues.append(label + f" [{lg}]：源或目标语言版本缺失/重复")
            elif not has_link(source[1], targets[0]):
                issues.append(label + f" [{lg}]：标记已完成，但正文无真实链接")
    return sorted(set(issues))


def load(vault):
    # 复用现有 frontmatter 契约；无须新增 YAML 依赖。
    article_dir = vault / "03-文章"
    if not article_dir.is_dir():
        raise ValueError("缺少 03-文章 目录")
    articles, keys = [], set()
    for path in sorted(article_dir.rglob("*.md")):
        if path.name.startswith("_"):
            continue
        fm, body = audit.parse_frontmatter(path.read_text(encoding="utf-8"))
        if not fm or not fm.get("article_id"):
            continue
        key = fm["article_id"], fm.get("lang")
        if key in keys:
            raise ValueError(f"重复文章/语言：{key}")
        keys.add(key)
        articles.append((fm, body, path))
    return articles


def export_article(articles, aid, lang):
    source = next((a for a in articles if (a[0]["article_id"], a[0].get("lang")) == (aid, lang)), None)
    if not source:
        raise ValueError("找不到该文章/语言")
    if source[0].get("status") not in ("ready", "translated", "published"):
        raise ValueError("文章尚未达到 ready/translated/published，不可导出发布稿")
    targets, errors = {}, []
    for a in articles:
        if a[0].get("lang") == lang:
            for key in (a[0]["article_id"], a[2].stem):
                targets[key] = a
    body = public_body(source[1]).strip() + "\n"

    def replace(m):
        raw = m.group(1)
        target = targets.get(wiki_target(raw, lang))
        if not target or target[0].get("status") != "published" or not valid_url(target[0].get("url")):
            errors.append(raw.split("|", 1)[0])
            return m.group()
        url = target[0]["url"]
        # Wiki 标题锚点和站点锚点无统一映射，禁止猜测。
        if "#" in raw.split("|", 1)[0]:
            errors.append(raw + "（需确认站点锚点）")
            return m.group()
        label = raw.split("|", 1)[1] if "|" in raw else target[0].get("title", target[0]["article_id"])
        label = re.sub(r"([\\\[\]*_`~])", r"\\\1", html.escape(label, quote=False))
        return f"[{label}]({url})"

    # 导出时逐行保留代码示例和注释；仅转换真正出现在正文的 wiki 链接。
    visible = prose(body)
    if re.search(r"!\[\[", visible):
        raise ValueError("正文含 Obsidian 图片/嵌入语法，需先映射为站点图片地址")
    body = WIKI.sub(lambda m: replace(m) if visible[m.start():m.end()] == m.group() else m.group(), body)
    if errors:
        raise ValueError("缺少同语言已发布 URL 或锚点映射：" + "、".join(sorted(set(errors))))
    return body


def feedback_csv(articles):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["article_id", "lang", "url", "period_start", "period_end", "query", "impressions", "clicks", "ctr", "average_position", "index_status", "engine", "prompt", "checked_at", "cited_url", "evidence", "next_action"])
    for fm, _body, _path in articles:
        if fm.get("status") == "published" and valid_url(fm.get("url")):
            writer.writerow([fm["article_id"], fm["lang"], fm["url"]] + [""] * 14)
    return out.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault", type=Path, default=Path(__file__).resolve().parent.parent)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory", help="列出文章状态与发布资料缺口")
    p = sub.add_parser("links", help="核对矩阵中已完成的正文链接")
    p.add_argument("--lang", default="", choices=[""] + audit.LANGS)
    p = sub.add_parser("export", help="按真实 URL 导出发布稿；源稿不变，不执行上线")
    p.add_argument("--article", required=True)
    p.add_argument("--lang", default="zh-Hant", choices=audit.LANGS)
    p.add_argument("--output", type=Path)
    p = sub.add_parser("feedback", help="仅为已发布页面生成空白效果记录 CSV")
    p.add_argument("--output", type=Path)
    args = ap.parse_args()
    try:
        articles = load(args.vault)
        if args.command == "links":
            matrix = (args.vault / "01-索引/内链矩阵.md").read_text(encoding="utf-8")
            issues = link_issues(articles, matrix, args.lang)
            print("\n".join(issues) if issues else "已完成的矩阵链接：正文核验通过")
            return int(bool(issues))
        if args.command == "inventory":
            for fm, _body, _path in articles:
                missing = [k for k in ("url", "publish_date", "author_url") if not fm.get(k)]
                print(f"{fm['article_id']} [{fm.get('lang')}] {fm.get('status')} / {fm.get('pipeline_stage', '未记录')} | 待补：{', '.join(missing) or '无'}")
            return 0
        output = export_article(articles, args.article, args.lang) if args.command == "export" else feedback_csv(articles)
        if args.output:
            # 不覆盖文章、既有成果或符号链接；目录须由操作者明确创建。
            with args.output.open("x", encoding="utf-8", newline="") as handle:
                handle.write(output)
            print(args.output)
        else:
            print(output, end="")
        return 0
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
