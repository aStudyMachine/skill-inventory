"""检查 Windows 客户端同步和安装的关键状态转换。"""

from http.client import IncompleteRead
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZipFile

from skill_inventory import cli, state, sync


class ClientSettingsTest(TestCase):
    def test_remembered_login_is_separate_from_session_and_bound_to_server(self):
        credentials = {}
        backend = Mock()
        backend.get_password.side_effect = lambda _, key: credentials.get(key)
        backend.set_password.side_effect = lambda _, key, value: credentials.update({key: value})
        backend.delete_password.side_effect = lambda _, key: credentials.pop(key)
        with patch.object(state, "vault", return_value=(backend, "测试凭据库")):
            server = "http://127.0.0.1:8787"
            state.remember_login(server, "reader", "测试密码")
            state.save_session("测试会话")
            state.clear_session()
            self.assertEqual(state.remembered_login(server), ("reader", "测试密码"))
            self.assertIsNone(state.remembered_login("http://127.0.0.1:8788"))
            state.forget_login()
            self.assertIsNone(state.remembered_login(server))
            with self.assertRaises(state.LoginRequired):
                state.get_session()

    def test_worker_picks_up_shorter_interval_without_restart(self):
        clock = 0
        sync_times = []

        def run_sync():
            sync_times.append(clock)
            return True, 300

        def sleep(seconds):
            nonlocal clock
            clock += seconds

        with (
            patch.object(state, "lock"),
            patch.object(cli, "stop_signal") as stop,
            patch.object(cli, "run_sync", side_effect=run_sync),
            patch.object(state, "state", side_effect=lambda: {"interval": 5 if clock >= 2 else 300}),
            patch.object(cli.time, "monotonic", side_effect=lambda: clock),
            patch.object(cli.time, "sleep", side_effect=sleep),
        ):
            stop.return_value.exists.side_effect = lambda: len(sync_times) == 2
            cli.worker()
        self.assertEqual(sync_times, [0, 5])


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
            user={"demo": "latest"}, resolved={"demo@latest": "1.0.0"}, userRoot=str(root),
        )
        package = BytesIO()
        with ZipFile(package, "w") as archive:
            archive.writestr("SKILL.md", "---\nname: demo\ndescription: 用例\n---\n")
        self.archive = package.getvalue()
        self.path = state.install("demo", "1.0.0", self.archive)
        state.save(self.data)
        token = patch.object(state, "get_session", return_value="unused")
        token.start()
        self.addCleanup(token.stop)

    def test_project_uses_only_its_own_choices(self):
        project = state.ROOT / "project"
        self.data["projects"] = {
            str(project): {"demo": "1.0.0"},
            str(project / "nested"): {},
        }
        self.assertEqual(sync.selected(self.data, state.ROOT), {"demo": "latest"})
        self.assertEqual(sync.selected(self.data, project / "src"), {"demo": "1.0.0"})
        self.assertEqual(sync.selected(self.data, project / "nested"), {})

    def test_interrupted_download_preserves_last_successful_version(self):
        with patch.object(sync.Api, "get", side_effect=[
            self.account, [{"name": "demo", "version": "2.0.0"}], IncompleteRead(b"partial"),
        ]):
            self.assertFalse(sync.sync(self.data))
        self.assertEqual(state.state()["resolved"], {"demo@latest": "1.0.0"})
        self.assertEqual(state.installed(), [self.path])

    def test_catalog_removes_unavailable_skill_and_preserves_last_snapshot_offline(self):
        root = state.ROOT
        directory = state.skills_dir(root)
        managed = state.install("demo", "1.0.0", self.archive, directory)
        manual = directory / "manual"
        manual.mkdir()
        skill = {"name": "demo", "version": "1.0.0", "description": "用例"}
        self.data["catalog"] = {"demo": skill}
        self.data["placements"] = {str(root): {"demo@latest": "1.0.0"}}
        with patch.object(sync.Api, "get", side_effect=OSError("断网")):
            self.assertFalse(sync.sync(self.data))
        self.assertEqual(state.state()["catalog"], {"demo": skill})
        self.assertTrue(managed.exists())

        with patch.object(sync.Api, "get", side_effect=[self.account, []]):
            sync.sync(self.data)
        self.assertEqual(state.state()["catalog"], {})
        self.assertFalse(managed.exists())
        self.assertTrue(manual.exists())

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

    def test_state_write_retries_a_temporary_windows_sharing_error(self):
        replace = Path.replace
        errors = [PermissionError("暂时被占用")]

        def briefly_blocked(source, destination):
            if errors:
                raise errors.pop()
            return replace(source, destination)

        self.data["interval"] = 60
        with patch.object(Path, "replace", briefly_blocked):
            state.save(self.data)
        self.assertEqual(state.state()["interval"], 60)

    def test_migrates_to_user_and_project_directories_with_distinct_rules(self):
        enabled, pinned, untouched = [state.ROOT / name for name in ("enabled", "pinned", "untouched")]
        for project in (enabled, pinned, untouched):
            project.mkdir()
            cli.set_target(self.data, "add-project", project)
        self.data["projects"][str(pinned)]["demo"] = "1.0.0"
        self.data["projects"][str(enabled)]["demo"] = "latest"

        with patch.object(sync.Api, "get", side_effect=[
            self.account, [{"name": "demo", "version": "2.0.0"}], self.archive, self.archive,
        ]) as request:
            self.assertTrue(sync.sync(self.data), self.data["issues"])
        self.assertEqual(request.call_count, 4)
        self.assertFalse(self.path.exists())
        for root, version in [(state.ROOT, "2.0.0"), (enabled, "2.0.0"), (pinned, "1.0.0")]:
            destination = state.skills_dir(root) / f"demo--{version}"
            self.assertTrue((destination / "SKILL.md").is_file())
            self.assertTrue(state.owned(destination))
        self.assertFalse(state.skills_dir(untouched).exists())

        cli.set_target(self.data, "remove-project", enabled)
        new_user = state.ROOT / "new-user"
        new_user.mkdir()
        cli.set_target(self.data, "set-user-root", new_user)
        with patch.object(sync.Api, "get", side_effect=OSError("断网")):
            self.assertFalse(sync.sync(self.data))
        self.assertTrue(state.installed(state.skills_dir(state.ROOT)))
        self.assertFalse(state.installed(state.skills_dir(new_user)))
        with patch.object(sync.Api, "get", side_effect=[
            self.account, [{"name": "demo", "version": "2.0.0"}], self.archive,
        ]):
            self.assertTrue(sync.sync(self.data), self.data["issues"])
        self.assertFalse(state.installed(state.skills_dir(enabled)))
        self.assertFalse(state.installed(state.skills_dir(state.ROOT)))
        self.assertTrue(state.installed(state.skills_dir(new_user)))

        with patch.object(sync.Api, "get", side_effect=[self.account, []]):
            self.assertFalse(sync.sync(self.data))
        self.assertFalse(state.installed(state.skills_dir(pinned)))
        self.assertFalse(state.installed(state.skills_dir(new_user)))

    def test_default_user_root_created_only_for_selected_skill(self):
        self.data.pop("userRoot")
        self.data["user"].clear()
        with patch.object(Path, "home", return_value=state.ROOT):
            root = state.ROOT / ".skills-inv"
            available = [{"name": "demo", "version": "2.0.0"}]
            with patch.object(sync.Api, "get", side_effect=[self.account, available]):
                self.assertTrue(sync.sync(self.data))
            self.assertEqual(sync.user_root(self.data), root)
            self.assertFalse(root.exists())
            self.data["user"]["demo"] = "latest"
            with patch.object(sync.Api, "get", side_effect=[self.account, available, self.archive]):
                self.assertTrue(sync.sync(self.data))
            self.assertTrue((state.skills_dir(root) / "demo--2.0.0/SKILL.md").is_file())

    def test_demo_default_layout_migrates_managed_files_and_preserves_manual_files(self):
        self.data.pop("userRoot")
        with patch.object(Path, "home", return_value=state.ROOT), patch.dict(os.environ, {
            "SKILL_INVENTORY_DEMO_LAYOUT": "1",
        }):
            root = sync.default_user_root()
            old_directory = state.skills_dir(root)
            old = state.install("demo", "1.0.0", self.archive, old_directory)
            manual = old_directory / "manual"
            manual.mkdir()
            self.data["placements"] = {str(root): {"demo@latest": "1.0.0"}}
            with patch.object(sync.Api, "get", side_effect=OSError("断网")):
                self.assertFalse(sync.sync(self.data))
            self.assertTrue(old.is_dir())
            self.assertEqual(sync.desired_path(self.data, root, "demo", "latest"), old)
            with patch.object(sync.Api, "get", side_effect=[
                self.account, [{"name": "demo", "version": "1.0.0"}], self.archive,
            ]):
                self.assertTrue(sync.sync(self.data), self.data["issues"])
            self.assertTrue((root / "skills/demo--1.0.0/SKILL.md").is_file())
            self.assertFalse(old.exists())
            self.assertTrue(manual.is_dir())
            self.assertEqual(sync.installation_directory(state.ROOT / "project"),
                             state.skills_dir(state.ROOT / "project"))

    def test_unavailable_project_keeps_its_last_successful_version(self):
        project = state.ROOT / "project"
        project.mkdir()
        cli.set_target(self.data, "add-project", project)
        self.data["projects"][str(project)]["demo"] = "latest"
        available = [{"name": "demo", "version": "1.0.0"}]
        with patch.object(sync.Api, "get", side_effect=[self.account, available, self.archive]):
            self.assertTrue(sync.sync(self.data))
        moved = project.with_name("unmounted")
        project.rename(moved)
        with patch.object(sync.Api, "get", side_effect=[self.account, available]):
            self.assertFalse(sync.sync(self.data))
        self.assertFalse(project.exists())
        self.assertEqual(sync.version_at(state.state(), project, "demo@latest"), "1.0.0")
        moved.rename(project)
        with patch.object(sync.Api, "get", side_effect=OSError("断网")):
            self.assertFalse(sync.sync(self.data))
        self.assertTrue(state.installed(state.skills_dir(project)))
