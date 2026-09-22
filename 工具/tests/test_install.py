import ast
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.source = base / 'source "quoted"'
        self.source.mkdir()
        shutil.copy2(ROOT / "install.sh", self.source / "install.sh")
        shutil.copytree(ROOT / "skills", self.source / "skills", ignore=shutil.ignore_patterns("__pycache__"))
        self.dest = base / "installed skills"
        self.agents = base / "agent skills"

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, *extra):
        return subprocess.run(["bash", str(self.source / "install.sh"),
                               "--skills-dir", str(self.dest), "--agents-dir", str(self.agents), *extra],
                              capture_output=True, text=True)

    def test_shared_install_and_portable_python(self):
        original = (self.source / "skills/seo-writing-openx/scripts/check_geo.py").read_bytes()
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("seo-writing-openx", "seo-geo-check"):
            self.assertEqual((self.agents / name).resolve(), (self.dest / name).resolve())
        script = self.dest / "seo-writing-openx/scripts/check_geo.py"
        ast.parse(script.read_text())
        docs = (self.dest / "seo-geo-check/SKILL.md").read_text()
        command = next(line for line in docs.splitlines() if line.startswith("python3 "))
        self.assertEqual(shlex.split(command)[1], str(self.dest.resolve() / "seo-geo-check/scripts/audit_d.py"))
        command_args = shlex.split(command)
        result = subprocess.run(command_args[:2] + ["missing-test-article.md"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("读不到文章：missing-test-article.md", result.stdout)
        self.assertNotIn("<VAULT_ROOT>", script.read_text())
        self.assertEqual((self.source / "skills/seo-writing-openx/scripts/check_geo.py").read_bytes(), original)

    def test_existing_agent_directory_requires_force(self):
        p = self.agents / "seo-writing-openx"
        p.mkdir(parents=True)
        (p / "custom.txt").write_text("keep")
        self.assertNotEqual(self.install().returncode, 0)
        self.assertEqual((p / "custom.txt").read_text(), "keep")
        self.assertFalse(self.dest.exists())
        result = self.install("--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(p.is_symlink())
        self.assertTrue(list(self.dest.parent.glob(".openx-install-backups/*/agents-seo-writing-openx/custom.txt")))

    def test_skip_then_force_preserves_backup(self):
        self.assertEqual(self.install().returncode, 0)
        custom = self.dest / "seo-writing-openx/custom.txt"
        custom.write_text("local edit")
        self.assertEqual(self.install().returncode, 0)
        self.assertTrue(custom.exists())
        result = self.install("--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(custom.exists())
        self.assertTrue(list(self.dest.parent.glob(".openx-install-backups/*/skills-seo-writing-openx/custom.txt")))

    def test_default_agent_symlink_overlap_rejected(self):
        # Patch only this temporary installer to emulate Path.home without changing HOME.
        fake_home = self.source.parent / "fake-home"
        dest = fake_home / ".claude/skills"
        dest.mkdir(parents=True)
        (fake_home / ".agents").mkdir()
        (fake_home / ".agents/skills").symlink_to(dest, target_is_directory=True)
        sentinel = dest / "keep.txt"
        sentinel.write_text("keep")
        installer = self.source / "install.sh"
        installer.write_text(installer.read_text().replace("Path.home()", "Path(" + repr(str(fake_home)) + ")"))
        result = subprocess.run(["bash", str(installer), "--agents", "--force"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertFalse((dest / "seo-writing-openx").exists())

    def test_source_destination_overlap_rejected(self):
        result = self.install("--skills-dir", str(self.source / "skills"))
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.source / "skills/seo-writing-openx/SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
