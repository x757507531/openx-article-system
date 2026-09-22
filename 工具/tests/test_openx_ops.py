import contextlib
import importlib.util
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import openx_ops as ops


def article(aid, body="", lang="zh-Hant", status="published", url=None):
    return ({"article_id": aid, "lang": lang, "source_lang": "zh-Hant",
             "status": status, "title": "测试", "url": url or f"https://openx.test/{lang}/{aid}"},
            body, Path(f"{aid}-slug.md"))


MATRIX = """| 需修改的旧文 | 链向 | 完成 |
|---|---|---|
| ~~OX-0001~~ | ~~OX-0002~~ | ✅ 已落实 |
"""


class LinkTests(unittest.TestCase):
    def test_completed_without_body_link_fails(self):
        self.assertTrue(ops.link_issues([article("OX-0001"), article("OX-0002")], MATRIX))

    def test_alias_and_heading_link(self):
        self.assertFalse(ops.link_issues([article("OX-0001", "正文 [[OX-0002-slug#概念|定义]]。"), article("OX-0002")], MATRIX))

    def test_work_code_and_comments_not_evidence(self):
        for body in ["`[[OX-0002-slug]]`", "```md\n[[OX-0002-slug]]\n```", "<!-- [[OX-0002-slug]] -->", "## 内链清单\n[[OX-0002-slug]]", "![[OX-0002-slug]]", "    [[OX-0002-slug]]", r"\[[OX-0002-slug]]"]:
            with self.subTest(body=body):
                self.assertTrue(ops.link_issues([article("OX-0001", body), article("OX-0002")], MATRIX))

    def test_real_url_link(self):
        target = article("OX-0002")
        self.assertFalse(ops.link_issues([article("OX-0001", f"正文 [定义]({target[0]['url']})"), target], MATRIX))

    def test_other_language_cannot_satisfy_link(self):
        self.assertTrue(ops.link_issues([article("OX-0001", "[[OX-0002-slug]]"), article("OX-0002", lang="en")], MATRIX))

    def test_explicit_other_language_path_does_not_match(self):
        self.assertFalse(ops.has_link("[[03-文章/zh-Hant/OX-0002-slug]]", article("OX-0002", lang="en")))
        self.assertTrue(ops.has_link("[[03-文章/en/OX-0002-slug]]", article("OX-0002", lang="en")))

    def test_unfinished_idea_is_not_completed(self):
        self.assertFalse(ops.link_issues([], MATRIX.replace("✅ 已落实", "☐")))

    def test_source_language_default(self):
        self.assertFalse(ops.link_issues([article("OX-0001", "[[OX-0002-slug]]"), article("OX-0001", lang="en"), article("OX-0002")], MATRIX))


class ExportTests(unittest.TestCase):
    def test_export_keeps_source_and_strips_work_area(self):
        source = article("OX-0001", "# 标题\n\n正文 [[OX-0002-slug|定义]]。\n\n## 上稿用 SEO 資訊\n内部资料")
        before = source[1]
        result = ops.export_article([source, article("OX-0002")], "OX-0001", "zh-Hant")
        self.assertIn("[定义](https://openx.test/zh-Hant/OX-0002)", result)
        self.assertNotIn("内部资料", result)
        self.assertEqual(source[1], before)

    def test_unpublished_target_fails(self):
        with self.assertRaises(ValueError):
            ops.export_article([article("OX-0001", "[[OX-0002-slug]]"), article("OX-0002", status="ready")], "OX-0001", "zh-Hant")

    def test_no_cross_language_fallback(self):
        with self.assertRaises(ValueError):
            ops.export_article([article("OX-0001", "[[OX-0002-slug]]"), article("OX-0002", lang="en")], "OX-0001", "zh-Hant")

    def test_code_identical_to_body_link_stays_literal(self):
        result = ops.export_article([article("OX-0001", "正文 [[OX-0002-slug]]。\n\n`[[OX-0002-slug]]`"), article("OX-0002")], "OX-0001", "zh-Hant")
        self.assertIn("`[[OX-0002-slug]]`", result)
        self.assertIn("[测试](https://", result)

    def test_unknown_anchor_and_embeds_fail(self):
        for link in ["[[OX-0002-slug#规则]]", "![[photo.png]]"]:
            with self.subTest(link=link), self.assertRaises(ValueError):
                ops.export_article([article("OX-0001", link), article("OX-0002")], "OX-0001", "zh-Hant")

    def test_explicit_foreign_path_rejected(self):
        with self.assertRaises(ValueError):
            ops.export_article([article("OX-0001", "[[03-文章/en/OX-0002-slug]]"), article("OX-0002")], "OX-0001", "zh-Hant")

    def test_work_heading_in_code_or_comment_does_not_truncate(self):
        for sample in ["```markdown\n## 内链清单\nexample\n```", "<!--\n## 内链清单\n-->"]:
            body = "# 标题\n\n" + sample + "\n\n## 正文\n重要内容。\n"
            result = ops.export_article([article("OX-0001", body)], "OX-0001", "zh-Hant")
            self.assertIn("重要内容", result)
            self.assertEqual(result, body)

    def test_feedback_only_published_and_no_fabricated_metrics(self):
        result = list(ops.csv.reader(io.StringIO(ops.feedback_csv([article("OX-0001"), article("OX-0002", status="ready")]))))
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0]), len(result[1]))
        self.assertEqual(result[1][3:], [""] * 14)

    def test_reject_unsafe_urls(self):
        for url in ["javascript:alert(1)", "https://x.test/a)bad", "https://u:p@x.test", "https://example.com/x", "https://x.test/a\nb", "https://x.test:bad/a", "https://x.test/\x00"]:
            self.assertFalse(ops.valid_url(url))

    def test_target_title_cannot_inject_raw_html(self):
        target = article("OX-0002")
        target[0]["title"] = '<img src=x onerror=alert(1)>'
        result = ops.export_article([article("OX-0001", "[[OX-0002-slug]]"), target], "OX-0001", "zh-Hant")
        self.assertNotIn("<img", result)
        self.assertIn("&lt;img", result)


class WritebackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        shutil.copytree(TOOLS, self.vault / "工具", ignore=shutil.ignore_patterns("__pycache__", "tests"))
        (self.vault / "03-文章/zh-Hant").mkdir(parents=True)
        (self.vault / "01-索引").mkdir()
        self.path = self.vault / "03-文章/zh-Hant/OX-0001-test.md"
        self.path.write_text("---\narticle_id: OX-0001\nlang: zh-Hant\nstatus: ready\nurl:\npublish_date:\nslug: test\n---\n\n# 标题\n")
        langs = " | ".join(ops.audit.LANGS)
        (self.vault / "01-索引/文章总表.md").write_text(f"| article_id | 源语言标题 | 整体状态 |\n|---|---|---|\n| OX-0001 | 标题 | ready |\n\n| article_id | {langs} |\n|---|---|---|---|---|---|---|---|\n| OX-0001 | ready | — | — | — | — | — | — |\n\n| article_id | lang | slug | url | publish_date |\n|---|---|---|---|---|\n")
        (self.vault / "01-索引/关键词登记表.md").write_text("| 主关键词 | 归属文章 | 状态 |\n|---|---|---|\n| test | OX-0001 | ready |\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_writeback(self, *args):
        return subprocess.run([sys.executable, str(self.vault / "工具/writeback.py"), "--article", "OX-0001", "--lang", "zh-Hant", *args], capture_output=True, text=True)

    def test_published_requires_url_and_date_no_mutation(self):
        before = self.path.read_bytes()
        result = self.run_writeback("--status", "published")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.path.read_bytes(), before)

    def test_bad_date_fails(self):
        result = self.run_writeback("--status", "published", "--url", "https://openx.test/test", "--publish-date", "2026-02-30")
        self.assertEqual(result.returncode, 2)

    def test_valid_publication_dry_run(self):
        before = self.path.read_bytes()
        result = self.run_writeback("--status", "published", "--url", "https://openx.test/test", "--publish-date", "2026-09-22", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.path.read_bytes(), before)

    def test_ready_does_not_require_publication(self):
        self.assertEqual(self.run_writeback("--status", "ready", "--dry-run").returncode, 0)

    def test_quoted_published_cannot_clear_url(self):
        self.path.write_text(self.path.read_text().replace("status: ready", 'status: "published"').replace("url:\n", "url: https://openx.test/test\n").replace("publish_date:\n", 'publish_date: "2026-09-22"\n'))
        before = self.path.read_bytes()
        result = self.run_writeback("--url", "")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_url_update_keeps_existing_publication_date(self):
        self.path.write_text(self.path.read_text().replace("publish_date:\n", 'publish_date: "2026-09-22"\n'))
        result = self.run_writeback("--status", "published", "--url", "https://openx.test/new")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("https://openx.test/new | 2026-09-22", (self.vault / "01-索引/文章总表.md").read_text())

    def test_inbound_update_preserves_frontmatter_separator(self):
        target = self.path.with_name("OX-0002-test.md")
        target.write_text("---\narticle_id: OX-0002\nlang: zh-Hant\nstatus: ready\ninbound_links: []\n---\n# 标题\n")
        result = self.run_writeback("--outbound", "OX-0002")
        self.assertEqual(result.returncode, 0, result.stderr)
        fm, body = ops.audit.parse_frontmatter(target.read_text())
        self.assertEqual(fm["inbound_links"], ["OX-0001"])
        self.assertEqual(body, "# 标题\n")

    def test_export_will_not_overwrite_source_or_existing_file(self):
        before = self.path.read_bytes()
        result = subprocess.run([sys.executable, str(self.vault / "工具/openx_ops.py"),
                                 "export", "--article", "OX-0001", "--output", str(self.path)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.path.read_bytes(), before)


class GeoTests(unittest.TestCase):
    @staticmethod
    def geo():
        path = TOOLS.parent / "skills/seo-writing-openx/scripts/check_geo.py"
        spec = importlib.util.spec_from_file_location("cg_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_shared_d1_and_removed_d5(self):
        cg = self.geo()
        with tempfile.TemporaryDirectory() as vault:
            for block, expected in [("主词" + "字" * 60, "PASS"), ("主词短句", "FAIL"),
                                    ("主词目前" + "字" * 60, "FAIL"),
                                    ("主词截至2026年9月" + "字" * 60, "PASS"),
                                    ("主词" + "字" * 60 + "[源](https://x.test)", "FAIL")]:
                with self.subTest(expected=expected):
                    report = cg.Report()
                    cg.check_d(report, {"primary_keyword": "主词"}, "# 标题\n\n> " + block + "\n", vault, "OX-0001")
                    self.assertEqual(next(r[0] for r in report.rows if r[1] == "D1"), expected)
                    self.assertFalse(any(r[1] in ("D2", "D5") for r in report.rows))

    def test_d6_accepts_one_traceable_gain(self):
        cg = self.geo()
        with tempfile.TemporaryDirectory() as vault:
            gain = Path(vault) / "06-工作区/增益/OX-0001"
            gain.mkdir(parents=True)
            (gain / "gain.md").write_text("- 官方来源中可复核的独有发现与读者价值 https://openx.test/source\n")
            report = cg.Report()
            cg.check_d(report, {}, "# 标题\n", vault, "OX-0001")
            self.assertEqual(next(r[0] for r in report.rows if r[1] == "D6"), "PASS")

    def test_optional_faq_schema_has_no_e2_warning(self):
        cg = self.geo(); report = cg.Report()
        cg.check_e(report, "# 标题\n", {"Schema": "Article + BreadcrumbList + Person"}, "")
        self.assertFalse(any(r[1] == "E2" or (r[1] == "E1" and r[0] != "PASS") for r in report.rows))

    def test_blogposting_satisfies_article_contract(self):
        cg = self.geo(); report = cg.Report()
        cg.check_e(report, "# 标题\n", {"Schema": "BlogPosting + BreadcrumbList + Person"}, "")
        self.assertFalse(any(r[1] == "E1" and r[0] == "FAIL" for r in report.rows))

    def test_no_stale_faq_instruction_in_case_review(self):
        path = TOOLS.parent / "skills/seo-geo-check/scripts/audit_d.py"
        spec = importlib.util.spec_from_file_location("audit_d_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertNotIn("FAQ", mod.REVIEW_QUESTIONS["D19"])
        self.assertIn("正文对应", mod.REVIEW_QUESTIONS["D4"])
        self.assertTrue(Path(mod.CHECK_GEO).is_file())


if __name__ == "__main__":
    unittest.main()
