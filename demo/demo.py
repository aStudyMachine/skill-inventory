"""启动便携演示，管理隔离的服务、同步进程和项目。"""

import argparse
import contextlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

from fixtures import Session, issue_device, seed

BUNDLE = Path(__file__).resolve().parents[2]
RUNTIME = BUNDLE / "runtime"
PROJECTS = ("inherit", "pinned", "disabled")
SLUG = "sprint-brief"
DESKTOP = "Skill-Inventory-Client.exe"


def process_env(lab):
    # 覆盖发现路径和配置根，演示不会使用日常 Codex 的项目、账号或 Skill。
    os.environ.update(
        CODEX_HOME=str(lab / "codex"), LOCALAPPDATA=str(lab / "local"),
        USERPROFILE=str(lab / "profile"), HOME=str(lab / "profile"),
        APPDATA=str(lab / "profile" / "AppData" / "Roaming"),
        PATH=os.pathsep.join([str(RUNTIME / "codex/bin"), str(RUNTIME / "codex/codex-path"),
                              str(Path(os.environ["SystemRoot"]) / "System32")]),
    )
    for name in tuple(os.environ):
        if name.startswith(("CODEX_", "OPENAI_", "INVENTORY_", "SPRING_", "SERVER_")) and name != "CODEX_HOME":
            del os.environ[name]
    for name in ("PYTHONPATH", "PYTHONHOME", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"):
        os.environ.pop(name, None)


def credentials(lab):
    config = lab / "accounts.json"
    if not config.exists():
        accounts = {name: secrets.token_urlsafe(16) for name in ("admin", "demo-dev", "demo-qa", "demo-both")}
        with config.open("x", encoding="utf-8") as output:
            json.dump(accounts, output, indent=2)
    return json.loads(config.read_text(encoding="utf-8"))


def initialize_projects(lab):
    checkout = lab / "codex"
    checkout.mkdir(exist_ok=True)
    config = checkout / "config.toml"
    if not config.exists():
        settings = []
        for name in PROJECTS:
            project = lab / "projects" / name
            project.mkdir(parents=True, exist_ok=True)
            settings.append("[projects." + json.dumps(str(project), ensure_ascii=False) + "]\n"
                            'trust_level = "trusted"\n')
        config.write_text("\n".join(settings), encoding="utf-8")


def command(*args, cwd=BUNDLE, **options):
    return subprocess.run([sys.executable, "-X", "utf8", "-m", "skill_inventory.cli", *map(str, args)],
                          cwd=cwd, **options)


def start_server(lab, port, password):
    # 单独检查端口，避免把占用该端口的服务识别成演示进程。
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", port))
    env = dict(os.environ, INVENTORY_DB=str(lab / "inventory.db"), INVENTORY_ADMIN_PASSWORD=password)
    static = (BUNDLE / "app/web").as_uri() + "/"
    with (lab / "server.log").open("ab") as log:
        process = subprocess.Popen([
            str(RUNTIME / "java/bin/java.exe"), "-Dfile.encoding=UTF-8", "-jar",
            str(BUNDLE / "app/skill-inventory.jar"), f"--server.port={port}",
            "--server.address=127.0.0.1", f"--server.servlet.session.cookie.name=SKILL_INVENTORY_DEMO_{port}",
            "--spring.config.location=classpath:/application.properties",
            "--spring.web.resources.static-locations=" + static,
        ], cwd=lab, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    origin = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 45
        while process.poll() is None and time.monotonic() < deadline:
            try:
                Session(origin).login("admin", password)
                return process
            except OSError:
                time.sleep(.3)
        raise RuntimeError(f"网页和 API 启动失败，请查看 {lab / 'server.log'}")
    except BaseException:
        stop_process(process)
        raise


def stop_process(process):
    if process is not None and process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        process.wait(timeout=10)


def start_worker(lab):
    from skill_inventory import cli, state

    if cli.running():
        cli.control("stop")
    state.ROOT.mkdir(parents=True, exist_ok=True)
    cli.stop_signal().unlink(missing_ok=True)
    with (lab / "worker.log").open("ab") as log:
        return subprocess.Popen([sys.executable, "-X", "utf8", "-m", "skill_inventory.cli", "worker"],
                                cwd=lab, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)


def prepare(lab, origin, passwords):
    from argparse import Namespace

    from skill_inventory import cli, state

    if (lab / "seeded").exists():
        previous = (lab / "seeded").read_text(encoding="utf-8")
        if previous != origin:
            raise ValueError("当前数据已绑定其他端口。使用原端口，或用 --fresh 开始新一轮。")
        return
    pending = lab / "seeding"
    if pending.exists():
        raise ValueError("上次初始化中断。保留现场，使用 --fresh 开始新一轮。")
    pending.touch()
    seed(origin, passwords, lab)
    token = issue_device(origin, passwords["demo-dev"])
    initialize_projects(lab)
    with state.lock("state"):
        data = state.state()
        cli.bind(data, origin, 5, token)
        cli.select(data, Namespace(action="enable", slug=SLUG, version="latest", project=None))
        cli.select(data, Namespace(action="enable", slug=SLUG, version="1.5.1",
                                   project=lab / "projects/pinned"))
        cli.select(data, Namespace(action="disable", slug=SLUG, project=lab / "projects/disabled"))
    command("sync", check=True)
    pending.write_text(origin, encoding="utf-8")
    pending.replace(lab / "seeded")


def visible(lab):
    result = {}
    for name in PROJECTS:
        response = command("codex", "--list-skills", cwd=lab / "projects" / name,
                           capture_output=True, encoding="utf-8", check=True)
        if response.stderr:
            print(response.stderr, end="", file=sys.stderr)
        result[name] = [
            Path(item["path"]).parent.name.removeprefix(SLUG + "--")
            for item in json.loads(response.stdout) if item["name"] == SLUG and item["enabled"]
        ]
        print(f"{name:8} {', '.join(result[name]) or '未启用'}")
    return result


def verify_web(origin):
    class Assets(HTMLParser):
        paths = set()

        def handle_starttag(self, tag, attributes):
            for attribute, value in attributes:
                if (tag, attribute) in {("script", "src"), ("link", "href")} and value.startswith("/assets/"):
                    self.paths.add(value)

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    parser = Assets()
    with opener.open(origin, timeout=3) as response:
        parser.feed(response.read().decode("utf-8"))
    if not parser.paths:
        raise ValueError("网页首页缺少 Vue 构建资源")
    for asset in sorted(parser.paths):
        with opener.open(origin + asset, timeout=3) as response:
            if not response.read(1):
                raise ValueError(f"网页资源为空：{asset}")


def choose_lab(args):
    data = BUNDLE / "demo-data"
    data.mkdir(exist_ok=True)
    pointer = data / "current"
    if args.fresh or not pointer.exists():
        lab = data / ("run-" + secrets.token_hex(6))
        lab.mkdir()
        pointer.write_text(lab.name, encoding="ascii")
    return current_lab(pointer)


def current_lab(pointer):
    name = pointer.read_text(encoding="ascii")
    if not name.startswith("run-") or len(name) != 16 or any(ch not in "0123456789abcdef" for ch in name[4:]):
        raise ValueError("演示目录索引无效，请使用 --fresh")
    return pointer.parent / name


def main():
    import msvcrt

    parser = argparse.ArgumentParser(description="Skill Inventory 便携演示")
    parser.add_argument("--fresh", action="store_true", help="新建一轮独立数据，保留旧数据")
    parser.add_argument("--port", type=int, default=18747, help="本机端口，默认 18747")
    parser.add_argument("--no-browser", action="store_true", help="启动时不打开默认浏览器")
    parser.add_argument("--verify", action="store_true", help="验证全新数据的三项目启用状态并退出")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口须为 1024 至 65535")
    # 同一包内同时只开一个菜单，防止多套进程写入同一轮数据。
    data = BUNDLE / "demo-data"
    data.mkdir(exist_ok=True)
    with (data / "demo.lock").open("a+b") as lock:
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise ValueError("此演示包已启动，请使用已有窗口") from None
        run(args)


def run(args):
    lab = choose_lab(args)
    process_env(lab)
    passwords = credentials(lab)
    origin = f"http://127.0.0.1:{args.port}"
    backend = worker = desktop = None
    try:
        backend = start_server(lab, args.port, passwords["admin"])
        prepare(lab, origin, passwords)
        worker = start_worker(lab)
        print(f"网页  {origin}\nAPI   {origin}/api/v1\n数据  {lab}", flush=True)
        if args.verify:
            verify_web(origin)
            expected = {"inherit": ["2.0.0"], "pinned": ["1.5.1"], "disabled": []}
            actual = visible(lab)
            if actual != expected:
                raise ValueError(f"三项目结果不符，预期 {expected}，实际 {actual}")
            if worker.poll() is not None:
                raise ValueError("后台同步退出，请查看 worker.log")
            return
        if not args.no_browser:
            webbrowser.open(origin)
        desktop = start_desktop()
        menu = ("1 查看三项目  2 客户端状态  3 立即同步  4 暂停/恢复网页和 API\n"
                "5 显示演示账号  6 打开演示数据目录  7 客户端命令窗口  8 打开桌面客户端  Q 退出")
        while True:
            print(menu)
            choice = input("> ").strip().lower()
            try:
                if choice == "1":
                    visible(lab)
                elif choice == "2":
                    command("status")
                elif choice == "3":
                    command("sync")
                elif choice == "4":
                    if backend is not None:
                        stop_process(backend)
                        backend = None
                        print("网页和 API 已暂停，后台同步继续。")
                    else:
                        backend = start_server(lab, args.port, passwords["admin"])
                        print("网页和 API 已恢复。浏览器刷新后重新登录。")
                elif choice == "5":
                    for user, password in passwords.items():
                        print(f"{user:10} {password}")
                elif choice == "6":
                    os.startfile(lab)
                elif choice == "7":
                    interactive_shell(lab)
                elif choice == "8":
                    if desktop.poll() is not None:
                        desktop = start_desktop()
                elif choice == "q":
                    break
            except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
                print(error, file=sys.stderr)
    except (EOFError, KeyboardInterrupt):
        print("\n退出演示")
    finally:
        # 显示窗口退出后，本次演示的服务和后台进程均结束。
        try:
            stop_process(desktop)
            if worker is not None:
                try:
                    command("stop", timeout=12)
                except subprocess.TimeoutExpired:
                    pass
                stop_process(worker)
        finally:
            stop_process(backend)


def interactive_shell(lab):
    # 提供随包 CLI，项目路径相对于命令窗口的初始目录。
    command_path = BUNDLE / "bin"
    env = dict(os.environ, PATH=str(command_path) + os.pathsep + os.environ["PATH"])
    shell = Path(os.environ["SystemRoot"]) / "System32/cmd.exe"
    subprocess.Popen([str(shell), "/d", "/k", "echo Use inventory --help or cd projects\\inherit."],
                     cwd=lab, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)


def start_desktop():
    return subprocess.Popen([str(BUNDLE / DESKTOP)], cwd=BUNDLE)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"演示启动或运行失败：{error}", file=sys.stderr)
        raise SystemExit(1) from None
