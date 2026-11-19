"""启动便携演示，管理服务、演示数据和同步进程。"""

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
from urllib.parse import urlsplit
import webbrowser

from fixtures import Session, seed

BUNDLE = Path(__file__).resolve().parents[2]
RUNTIME = BUNDLE / "runtime"
DESKTOP = "Skill-Inventory-Client.exe"
DEFAULT_PORT = 18747
# 公开的本地验收账号，只用于便携演示数据库。
DEMO_PASSWORD = "88888888"
DEMO_ACCOUNTS = dict.fromkeys(("admin", "demo-dev", "demo-qa", "demo-both"), DEMO_PASSWORD)


def process_env(lab):
    # 只指定本轮客户端状态目录，目录选择器和同步使用真实设备路径。
    os.environ["SKILL_INVENTORY_STATE_DIR"] = str(lab / "local/SkillInventory")
    os.environ["SKILL_INVENTORY_DEMO_LAYOUT"] = "1"
    for name in tuple(os.environ):
        if name.startswith(("CODEX_", "OPENAI_", "INVENTORY_", "SPRING_", "SERVER_")) and name != "CODEX_HOME":
            del os.environ[name]
    for name in ("PYTHONPATH", "PYTHONHOME", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"):
        os.environ.pop(name, None)


def credentials(lab):
    # 旧演示数据仍使用原来的初始化密码。
    config = lab / "accounts.json"
    return json.loads(config.read_text(encoding="utf-8")) if config.is_file() else DEMO_ACCOUNTS


def command(*args, cwd=BUNDLE, **options):
    return subprocess.run([sys.executable, "-X", "utf8", "-m", "skill_inventory.cli", *map(str, args)],
                          cwd=cwd, **options)


def probe_port(port):
    """用独占绑定检查端口，传入 0 时由 Windows 分配可用端口。"""
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as error:
            if error.winerror not in (10013, 10048):
                raise
            return None
        return listener.getsockname()[1]


def choose_port(lab, requested):
    if requested is not None:
        return requested
    seeded = lab / "seeded"
    preferred = urlsplit(seeded.read_text(encoding="utf-8")).port if seeded.is_file() else DEFAULT_PORT
    for candidate in dict.fromkeys([preferred, DEFAULT_PORT, 0]):
        if (port := probe_port(candidate)) is not None:
            if port != preferred:
                print(f"端口 {preferred} 不可用，已自动选择 {port}。", flush=True)
            return port
    raise ValueError("无法分配本机演示端口")


def start_server(lab, port, password):
    # 单独检查端口，避免把占用该端口的服务识别成演示进程。
    if probe_port(port) is None:
        raise ValueError(f"端口 {port} 不可用。直接启动可自动选择端口，也可用 --port 指定其他端口。")
    env = dict(os.environ, INVENTORY_DB=str(lab / "inventory.db"), INVENTORY_ADMIN_PASSWORD=password)
    static = (BUNDLE / "app/web").as_uri() + "/"
    with (lab / "server.log").open("ab") as log:
        process = subprocess.Popen([
            str(RUNTIME / "java/bin/java.exe"), "-Dfile.encoding=UTF-8", "-jar",
            str(BUNDLE / "app/skill-inventory.jar"), f"--server.port={port}",
            "--server.address=127.0.0.1", f"--server.servlet.session.cookie.name=SKILL_INVENTORY_DEMO_{port}",
            "--inventory.demo-initial-password=" + DEMO_PASSWORD,
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


def stop_old_servers():
    """只匹配使用本包 Java 和绝对 JAR 路径的历史演示服务。"""
    shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    env = dict(os.environ, SKILL_DEMO_JAVA=str(RUNTIME / "java/bin/java.exe"),
               SKILL_DEMO_JAR=str(BUNDLE / "app/skill-inventory.jar"))
    script = r"""
    $ErrorActionPreference = 'Stop'
    $jar = [regex]::Escape($env:SKILL_DEMO_JAR)
    $pattern = '(?:^|\s)-jar\s+(?:"' + $jar + '"|' + $jar + ')(?=\s|$)'
    foreach ($item in Get-CimInstance Win32_Process -Filter "Name='java.exe'") {
        if ($item.ExecutablePath -ne $env:SKILL_DEMO_JAVA -or $item.CommandLine -notmatch $pattern) { continue }
        $process = Get-Process -Id $item.ProcessId -ErrorAction SilentlyContinue
        if ($process -and -not $process.HasExited -and
            [math]::Abs(($process.StartTime - $item.CreationDate).TotalMilliseconds) -lt 1) {
            $process.Kill()
            if (-not $process.WaitForExit(10000)) { throw "Java PID $($item.ProcessId) did not exit" }
            Write-Output $item.ProcessId
        }
    }
    """
    result = subprocess.run([str(shell), "-NoProfile", "-NonInteractive", "-Command", script],
                            env=env, capture_output=True, text=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(f"无法检查或关闭历史演示服务：{result.stderr.strip()}")
    for pid in result.stdout.split():
        print(f"已关闭历史演示 Java 服务（PID {pid}）", flush=True)


def read_menu_line(restart):
    """等待菜单输入时也能接收来自同一演示包的重启请求。"""
    import msvcrt

    if not sys.stdin.isatty():
        return input("> ")
    print("> ", end="", flush=True)
    line = []
    while not restart.exists():
        if not msvcrt.kbhit():
            time.sleep(.1)
            continue
        key = msvcrt.getwch()
        if key == "\r":
            print()
            return "".join(line)
        if key in ("\x00", "\xe0"):
            msvcrt.getwch()
        elif key == "\b" and line:
            line.pop()
            print("\b \b", end="", flush=True)
        elif key.isprintable():
            line.append(key)
            print(key, end="", flush=True)
    print("\n收到重启请求，正在停止本轮演示。", flush=True)
    return None


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
    from skill_inventory import state

    seeded = lab / "seeded"
    pending = lab / "seeding"
    if not seeded.exists():
        if pending.exists():
            raise ValueError("上次初始化中断。保留现场，使用 --fresh 开始新一轮。")
        pending.touch()
        seed(origin, passwords, lab)
        pending.write_text(origin, encoding="utf-8")
        pending.replace(seeded)

    previous = seeded.read_text(encoding="utf-8")
    with state.lock("state"):
        data = state.state()
        if not data.get("server"):
            data["server"] = origin
            data["interval"] = 5
            state.save(data)
        elif data["server"] == previous and previous != origin:
            # 端口变更时保留同一演示数据库的会话和同步间隔。
            data["server"] = origin
            state.save(data)
    if previous != origin:
        seeded.write_text(origin, encoding="utf-8")


def verify_client_login(origin, passwords):
    from skill_inventory import sync

    account, session = sync.Api(origin).login("demo-dev", passwords["demo-dev"])
    api = sync.Api(origin, session)
    try:
        if api.get("/client-session") != account or account["username"] != "demo-dev":
            raise ValueError("无法验证客户端登录")
        names = {item["name"] for item in api.get("/skills")}
        if "qa-handbook" in names:
            raise ValueError("开发账号不应有 QA 技能的读取权限")
    finally:
        api.logout()


def verify_files(require_empty=False):
    from skill_inventory import state, sync

    data = state.state()
    if require_empty and (data["user"] or data["projects"]):
        raise ValueError("全新演示应没有预勾选的 Skill 或项目")
    for root in sync.scopes(data):
        directory = sync.installation_directory(root)
        print(f"{directory}", flush=True)
        files = state.installed(directory)
        for folder in files:
            print(f"  {folder.name}/SKILL.md")
        if not files:
            print("  没有已同步的受管 Skill")
        for key, version in data.get("placements", {}).get(root, {}).items():
            slug = key.split("@", 1)[0]
            file = state.package_path(slug, version, directory) / "SKILL.md"
            if not file.is_file():
                raise ValueError(f"已记录的 Skill 文件不存在：{file}")


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
    parser.add_argument("--restart", action="store_true", help="结束本包当前演示并重新启动")
    parser.add_argument("--port", type=int, help="指定本机端口。省略时优先复用上次端口或 18747，再自动分配")
    parser.add_argument("--no-browser", action="store_true", help="启动时不打开默认浏览器")
    parser.add_argument("--verify", action="store_true", help="验证网页、同步及本地 Skill 文件并退出")
    args = parser.parse_args()
    if args.port is not None and not 1024 <= args.port <= 65535:
        parser.error("端口须为 1024 至 65535")
    # 同一包内同时只开一个菜单，防止多套进程写入同一轮数据。
    data = BUNDLE / "demo-data"
    data.mkdir(exist_ok=True)
    restart = data / "restart.request"
    with (data / "demo.lock").open("a+b") as lock:
        deadline = time.monotonic() + 35
        while True:
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if not args.restart:
                    raise ValueError("此演示包已启动，可使用已有窗口或加 --restart") from None
                if time.monotonic() >= deadline:
                    raise ValueError("当前演示未退出，请在原窗口按 Q，再重试") from None
                restart.touch(exist_ok=True)
                time.sleep(.25)
        restart.unlink(missing_ok=True)
        stop_old_servers()
        run(args, restart)


def run(args, restart):
    lab = choose_lab(args)
    process_env(lab)
    passwords = credentials(lab)
    port = choose_port(lab, args.port)
    origin = f"http://127.0.0.1:{port}"
    backend = worker = desktop = None
    try:
        backend = start_server(lab, port, passwords["admin"])
        prepare(lab, origin, passwords)
        worker = start_worker(lab)
        print(f"网页  {origin}\nAPI   {origin}/api/v1\n数据  {lab}", flush=True)
        if args.verify:
            verify_web(origin)
            verify_client_login(origin, passwords)
            verify_files(require_empty=args.fresh)
            if worker.poll() is not None:
                raise ValueError("后台同步退出，请查看 worker.log")
            return
        print(f"首次打开桌面客户端，请使用 demo-dev 登录。演示密码：{passwords['demo-dev']}", flush=True)
        if not args.no_browser:
            webbrowser.open(origin)
        desktop = start_desktop()
        menu = ("1 查看已同步文件  2 客户端状态  3 立即同步  4 暂停/恢复网页和 API\n"
                "5 显示演示账号  6 打开演示数据目录  7 客户端命令窗口  8 打开桌面客户端  Q 退出")
        while True:
            print(menu)
            line = read_menu_line(restart)
            if line is None:
                break
            choice = line.strip().lower()
            try:
                if choice == "1":
                    verify_files()
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
                        backend = start_server(lab, port, passwords["admin"])
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
    subprocess.Popen([str(shell), "/d", "/k", "echo Use inventory --help."],
                     cwd=lab, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)


def start_desktop():
    return subprocess.Popen([str(BUNDLE / DESKTOP)], cwd=BUNDLE)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"演示启动或运行失败：{error}", file=sys.stderr)
        raise SystemExit(1) from None
