"""检查 Windows 客户端同步和安装的关键状态转换。"""

from http.client import IncompleteRead
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

from skill_inventory import state, sync


class SyncTest(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        codex_home = root / "codex"
        patches = patch.multiple(
            state, ROOT=root, CODEX_HOME=codex_home, PACKAGES=codex_home / "skills" / "managed"
        )
        patches.start()
        self.addCleanup(patches.stop)
        self.data = state.state()
        self.account = {"id": 1, "username": "reader"}
        self.data.update(
            server="http://127.0.0.1:8787", account=self.account,
            user={"demo": "latest"}, resolved={"demo@latest": "1.0.0"},
        )
        package = BytesIO()
        with ZipFile(package, "w") as archive:
            archive.writestr("SKILL.md", "---\nname: demo\ndescription: 用例\n---\n")
        self.path = state.install("demo", "1.0.0", package.getvalue())
        state.save(self.data)
        token = patch.object(state, "get_token", return_value="unused")
        token.start()
        self.addCleanup(token.stop)

    def test_project_override_uses_nearest_configured_directory(self):
        project = state.ROOT / "project"
        self.data["projects"] = {
            str(project): {"demo": "1.0.0"},
            str(project / "nested"): {"demo": "off"},
        }
        self.assertEqual(sync.selected(self.data, state.ROOT), {"demo": "latest"})
        self.assertEqual(sync.selected(self.data, project / "src"), {"demo": "1.0.0"})
        self.assertEqual(sync.selected(self.data, project / "nested"), {})

    def test_interrupted_download_preserves_last_successful_version(self):
        with patch.object(sync.Api, "get", side_effect=[
            self.account, [{"slug": "demo", "version": "2.0.0"}], IncompleteRead(b"partial"),
        ]):
            self.assertFalse(sync.sync(self.data))
        self.assertEqual(state.state()["resolved"], {"demo@latest": "1.0.0"})
        self.assertEqual(state.installed(), [self.path])

    def test_revocation_persists_even_when_windows_prevents_cleanup(self):
        def blocked(path):
            self.assertEqual(path, self.path)
            self.assertEqual(state.state()["resolved"], {})
            raise PermissionError("目录占用")

        with patch.object(sync.Api, "get", side_effect=[self.account, []]):
            with patch.object(state, "retire", side_effect=blocked):
                self.assertFalse(sync.sync(self.data))
        self.assertEqual(state.state()["resolved"], {})
        self.assertIn("目录占用", "\n".join(state.state()["issues"]))
        with patch.object(sync.Api, "get", side_effect=[self.account, []]):
            self.assertFalse(sync.sync(self.data))
        self.assertNotIn("目录占用", "\n".join(state.state()["issues"]))
        self.assertFalse(state.installed())

    def test_manual_installation_is_preserved(self):
        destination = state.package_path("demo", "2.0.0")
        destination.mkdir()
        manual = destination / "SKILL.md"
        manual.write_text("手动安装", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "安装冲突"):
            state.install("demo", "2.0.0", b"")
        self.assertEqual(manual.read_text(encoding="utf-8"), "手动安装")
