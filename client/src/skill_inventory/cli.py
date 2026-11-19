"""配置、运行和查询 Skill Inventory Windows 客户端。"""

import argparse
import getpass
from http.client import HTTPException
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from . import codex, state, sync


def arguments():
    parser = argparse.ArgumentParser(description="将 Skill 同步到指定用户级和项目级目录")
    commands = parser.add_subparsers(dest="action", required=True)
    configure = commands.add_parser("login", aliases=["configure"], help="使用账号密码登录")
    configure.add_argument("server", help="服务端地址，如 http://127.0.0.1:8787")
    configure.add_argument("username", help="账号")
    configure.add_argument("--interval", type=int, default=300, help="同步间隔，单位为秒（默认 300）")
    for name, help_text in [("enable", "在指定范围启用 Skill"), ("disable", "在指定范围停用 Skill")]:
        item = commands.add_parser(name, help=help_text)
        item.add_argument("name", help="Skill 名称")
        item.add_argument("--project", type=Path, help="项目目录")
        if name == "enable":
            item.add_argument("--version", default="latest", help="固定版本号，默认跟随最新版")
    commands.add_parser("logout", help="退出登录并清理受管副本")
    commands.add_parser("sync", help="立即同步")
    commands.add_parser("status", help="查看同步和启用状态")
    commands.add_parser("start", help="启动后台同步")
    commands.add_parser("stop", help="停止后台同步")
    commands.add_parser("worker", help=argparse.SUPPRESS)
    for name, description in [
        ("set-user-root", "指定用户级根目录"),
        ("add-project", "登记项目根目录，同步其生效的 Skill"),
        ("remove-project", "取消项目登记并在下次同步移除其受管文件"),
    ]:
        target = commands.add_parser(name, help=description)
        target.add_argument("directory", type=Path)
    launcher = commands.add_parser("codex", help="按当前项目配置启动 Codex")
    launcher.add_argument("--list-skills", action="store_true", help="显示 Codex 实际发现的受管 Skill")
    return parser.parse_args()


def configure(data, args):
    server, interval = login_settings(args.server, args.interval)
    login(data, server, args.username, getpass.getpass("密码："), interval)


def login_settings(server, interval):
    return sync.server_address(server), validate_interval(interval)


def validate_interval(interval):
    if not 5 <= interval <= 86400:
        raise ValueError("同步间隔须为 5 至 86400 秒")
    return interval


def login(data, server, username, password, interval):
    server, interval = login_settings(server, interval)
    account, session = sync.Api(server).login(username, password)
    try:
        try:
            previous = state.get_session()
        except state.LoginRequired:
            previous = None
        if previous and data.get("server"):
            sync.Api(data["server"], previous).logout()
        if (data.get("server"), data.get("account")) != (server, account):
            sync.revoke_all(data)
            data["issues"] = []
            data.pop("lastConnected", None)
            state.save(data)
            sync.cleanup(data)
            if data["issues"]:
                state.save(data)
                raise ValueError("先前账号的文件仍在使用，请关闭相关程序后重新登录")
        state.save_session(session)
        data.update(server=server, account=account, interval=interval)
        state.save(data)
    except Exception:
        sync.Api(server, session).logout()
        raise
    print(f"已登录 {account['username']}，同步间隔 {interval} 秒")


def logout(data):
    try:
        session = state.get_session()
    except state.LoginRequired:
        session = None
    if session and data.get("server"):
        sync.Api(data["server"], session).logout()
    data["issues"] = []
    sync.invalidate(data)
    sync.cleanup(data)
    state.save(data)
    print("已退出登录")
    for issue in data["issues"]:
        print(issue, file=sys.stderr)


def select(data, args):
    if not state.name_valid(args.name):
        raise ValueError("Skill 名称格式不正确")
    project = str(args.project.resolve(strict=True)) if args.project else None
    if project and not Path(project).is_dir():
        raise ValueError("项目路径必须是目录")
    if project and state.unsafe_directory(state.skills_dir(project)):
        raise ValueError("项目目录下的 .agents/skills 不能是链接")
    if project and Path(project) == sync.user_root(data):
        raise ValueError("项目根目录不能与用户级根目录相同")
    group = data["projects"].setdefault(project, {}) if project else data["user"]
    if args.action == "enable":
        if args.version != "latest" and not state.VERSION.fullmatch(args.version):
            raise ValueError("请指定有效的三段版本号或 latest")
        group[args.name] = args.version
    else:
        group.pop(args.name, None)
    state.save(data)


def set_target(data, action, directory):
    root = directory.resolve(strict=action != "remove-project")
    if action == "remove-project":
        if str(root) in data["projects"]:
            data.setdefault("placements", {}).setdefault(str(root), {})
        data["projects"].pop(str(root), None)
    else:
        directory = sync.installation_directory(root) if action == "set-user-root" else state.skills_dir(root)
        if not root.is_dir() or state.unsafe_directory(directory):
            raise ValueError(f"请选择有效目录，同步位置不能是链接：{directory}")
        if action == "set-user-root":
            if str(root) in data["projects"]:
                raise ValueError("用户级根目录不能与已登记项目相同")
            if root != sync.user_root(data):
                previous = str(sync.user_root(data))
                data.setdefault("placements", {}).setdefault(previous, {})
                previous_roots = data.setdefault("previousUserRoots", [])
                if previous not in previous_roots:
                    previous_roots.append(previous)
            data["userRoot"] = str(root)
        elif root == sync.user_root(data):
            raise ValueError("项目根目录不能与用户级根目录相同")
        else:
            data["projects"].setdefault(str(root), {})
    state.save(data)


def running():
    try:
        with state.lock("worker", wait=False):
            return False
    except ValueError:
        return True


def console_python():
    executable = Path(sys.executable)
    console = executable.with_name("python.exe")
    return str(console if executable.name.lower() == "pythonw.exe" and console.is_file() else executable)


def run_sync():
    with state.lock("state"):
        data = state.state()
        ok = sync.sync(data)
    for issue in data["issues"]:
        print(issue, file=sys.stderr)
    return ok, data["interval"]


def stop_signal():
    return state.ROOT / "stop"


def worker():
    with state.lock("worker", wait=False):
        while not stop_signal().exists():
            try:
                _, interval = run_sync()
            except (OSError, ValueError) as error:
                print(error, file=sys.stderr)
                interval = None
            started = time.monotonic()
            while not stop_signal().exists():
                if interval is not None:
                    try:
                        interval = state.state()["interval"]
                    except OSError:
                        pass
                remaining = (30 if interval is None else interval) - (time.monotonic() - started)
                if remaining <= 0:
                    break
                time.sleep(min(1, remaining))


def control(action):
    with state.lock("control"):
        if action == "start":
            if running():
                print("后台同步已运行")
                return
            with state.lock("state"):
                if not state.state().get("account"):
                    raise ValueError("请先运行 login 登录")
                state.get_session()
            stop_signal().unlink(missing_ok=True)
            log = state.ROOT / "worker.log"
            with log.open("wb") as output:
                process = subprocess.Popen(
                    [console_python(), "-m", "skill_inventory.cli", "worker"], stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
                )
            for _ in range(30):
                if running():
                    print("后台同步已启动")
                    return
                if process.poll() is not None:
                    break
                time.sleep(.1)
            raise ValueError(f"后台进程未能启动，请检查 {log}")
        if running():
            stop_signal().touch()
            for _ in range(120):
                if not running():
                    break
                time.sleep(.25)
            else:
                raise ValueError("后台进程正在结束本轮同步")
        print("后台同步已停止")


def discover(cwd, list_only=True):
    with state.lock("state"):
        data = state.state()
        paths = []
        for directory in sync.directories(data):
            if not state.unsafe_directory(directory):
                paths.extend(state.installed(directory))
        managed = {codex.key(path / "SKILL.md") for path in paths}
        desired = set()
        try:
            state.get_session()
            choices = sync.selected(data, cwd) if data.get("account") else {}
        except state.LoginRequired:
            choices = {}
        for slug, selection in choices.items():
            destination = sync.desired_path(data, cwd, slug, selection)
            if destination:
                path = codex.key(destination / "SKILL.md")
                if path in managed:
                    desired.add(path)
            else:
                print(f"{slug} ({selection}) 尚未同步，请查看 status", file=sys.stderr)
        config, discovered = codex.inspect(cwd)
        identified = {item["key"] for item in discovered}
        if desired - identified:
            raise ValueError("Codex 未发现这些已同步的 Skill。请检查根目录是否在 Codex 的发现范围内："
                             + "、".join(sorted(desired - identified)))
        options, conflicts = codex.launch_options(config, discovered, managed, desired)
        actual = []
        if list_only:
            _, inspected = codex.inspect(cwd, options)
            actual = [{"name": item["name"], "path": item["path"], "enabled": item["enabled"]}
                      for item in inspected if item["key"] in managed]
        return options, conflicts, actual


def launch(list_only):
    cwd = Path.cwd().resolve()
    options, conflicts, actual = discover(cwd, list_only)
    for conflict in conflicts:
        print(f"Skill 同名冲突，已保留现有文件并停用受管副本：{conflict}", file=sys.stderr)
    if list_only:
        print(json.dumps(actual, ensure_ascii=False, indent=2))
        return 0
    return subprocess.call([*codex.command(), *options], cwd=cwd)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    args = arguments()
    try:
        if args.action == "worker":
            worker()
            return 0
        if args.action in ("start", "stop"):
            control(args.action)
            return 0
        if args.action == "sync":
            ok, _ = run_sync()
            if ok:
                print("同步完成")
            return 0 if ok else 1
        if args.action == "codex":
            return launch(args.list_skills)
        with state.lock("state"):
            data = state.state()
            if args.action in ("login", "configure"):
                configure(data, args)
            elif args.action == "logout":
                logout(data)
            elif args.action == "status":
                print(json.dumps({"running": running(), **data}, ensure_ascii=False, indent=2))
            elif args.action in ("set-user-root", "add-project", "remove-project"):
                set_target(data, args.action, args.directory)
                print("同步目录设置已保存。可运行 sync 立即同步。")
            else:
                select(data, args)
                print("启用配置已保存。可运行 sync 立即同步。")
        return 0
    except (ImportError, KeyError, OSError, ValueError, HTTPException, sync.ApiError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
