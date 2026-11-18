"""配置、运行和查询 Skill Inventory Windows 客户端。"""

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from . import codex, state, sync


def arguments():
    parser = argparse.ArgumentParser(description="同步和启用 Skill Inventory 中的 Codex Skill")
    commands = parser.add_subparsers(dest="action", required=True)
    configure = commands.add_parser("configure", help="绑定服务端和设备令牌")
    configure.add_argument("server", help="服务端地址，如 http://127.0.0.1:8787")
    configure.add_argument("--interval", type=int, default=300, help="同步间隔，单位为秒（默认 300）")
    for name, help_text in [("enable", "启用 Skill 或覆盖版本"), ("disable", "停用 Skill"),
                            ("inherit", "取消项目覆盖，恢复继承")]:
        item = commands.add_parser(name, help=help_text)
        item.add_argument("slug", help="平台上的 Skill slug")
        item.add_argument("--project", type=Path, required=name == "inherit", help="项目目录")
        if name == "enable":
            item.add_argument("--version", default="latest", help="固定版本号，默认跟随最新版")
    commands.add_parser("sync", help="立即同步")
    commands.add_parser("status", help="查看同步和启用状态")
    commands.add_parser("start", help="启动后台同步")
    commands.add_parser("stop", help="停止后台同步")
    commands.add_parser("worker", help=argparse.SUPPRESS)
    launcher = commands.add_parser("codex", help="按当前项目配置启动 Codex")
    launcher.add_argument("--list-skills", action="store_true", help="显示 Codex 实际发现的受管 Skill")
    return parser.parse_args()


def configure(data, args):
    bind(data, args.server, args.interval)


def bind(data, server, interval, token=None):
    server = sync.server_address(server)
    if not 5 <= interval <= 86400:
        raise ValueError("同步间隔须为 5 至 86400 秒")
    if token is None:
        token = getpass.getpass("设备令牌：").strip()
    if not re.fullmatch("[a-zA-Z0-9_-]{43}", token):
        raise ValueError("设备令牌格式不正确")
    account = sync.Api(server, token).get("/device")
    if (data.get("server"), data.get("account")) != (server, account):
        sync.revoke_all(data)
        data.pop("lastConnected", None)
        state.save(data)
        sync.cleanup(data)
        if state.installed():
            state.save(data)
            raise ValueError("先前账号的文件仍在使用，请关闭相关程序后重新绑定")
    state.save_token(token)
    data.update(server=server, account=account, interval=interval)
    state.save(data)
    print(f"已绑定 {account['username']}，同步间隔 {interval} 秒")


def select(data, args):
    if not state.slug_valid(args.slug):
        raise ValueError("slug 格式不正确")
    project = str(args.project.resolve(strict=True)) if args.project else None
    if project and not Path(project).is_dir():
        raise ValueError("项目路径必须是目录")
    group = data["projects"].setdefault(project, {}) if project else data["user"]
    if args.action == "enable":
        if args.version != "latest" and not state.VERSION.fullmatch(args.version):
            raise ValueError("请指定有效的三段版本号或 latest")
        group[args.slug] = args.version
    elif args.action == "disable" and project:
        group[args.slug] = "off"
    else:
        group.pop(args.slug, None)
    if project and not group:
        data["projects"].pop(project, None)
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
                interval = 30
            deadline = time.monotonic() + interval
            while not stop_signal().exists() and time.monotonic() < deadline:
                time.sleep(.25)


def control(action):
    with state.lock("control"):
        if action == "start":
            if running():
                print("后台同步已运行")
                return
            with state.lock("state"):
                if "server" not in state.state():
                    raise ValueError("请先运行 configure")
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
        paths = state.installed()
        managed = {codex.key(path / "SKILL.md") for path in paths}
        desired = set()
        for slug, selection in sync.selected(data, cwd).items():
            version = data["resolved"].get(sync.selector(slug, selection))
            if version:
                path = codex.key(state.package_path(slug, version) / "SKILL.md")
                if path in managed:
                    desired.add(path)
            else:
                print(f"{slug} ({selection}) 尚未同步，请查看 status", file=sys.stderr)
        config, discovered = codex.inspect(cwd)
        identified = {item["key"] for item in discovered}
        if desired - identified:
            raise ValueError("Codex 未发现选定的受管 Skill，请检查配置和 status")
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
            if args.action == "configure":
                configure(data, args)
            elif args.action == "status":
                print(json.dumps({"running": running(), **data}, ensure_ascii=False, indent=2))
            else:
                select(data, args)
                print("启用配置已保存。可运行 sync 立即同步。")
        return 0
    except (ImportError, KeyError, OSError, ValueError, sync.ApiError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
