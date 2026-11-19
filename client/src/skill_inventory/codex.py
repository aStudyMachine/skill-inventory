"""从 Codex 的公开 app-server 接口读取实际 Skill 及配置。"""

import contextlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading


def command():
    native = shutil.which("codex.exe")
    if native:
        return [native]
    npm = shutil.which("codex.cmd")
    node = shutil.which("node.exe")
    if npm and node:
        script = Path(npm).parent / "node_modules/@openai/codex/bin/codex.js"
        if script.is_file():
            return [node, str(script)]
    raise ValueError("未找到 Codex CLI，请将原生 Codex 或 npm 版 Codex 和 Node.js 加入 PATH")


def rpc(cwd, requests, options=()):
    messages = [
        {"id": 0, "method": "initialize",
         "params": {"clientInfo": {"name": "skill-inventory", "version": "0.3.0"}}},
        {"method": "initialized"},
    ]
    messages.extend({"id": index, "method": method, "params": params}
                    for index, (method, params) in enumerate(requests, 1))
    process = subprocess.Popen(
        [*command(), *options, "app-server"], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW,
    )
    lines = queue.Queue()

    def read():
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    responses = {}
    try:
        process.stdin.write("".join(json.dumps(message) + "\n" for message in messages))
        process.stdin.flush()
        while len(responses) < len(messages) - 1:
            line = lines.get(timeout=20)
            if line is None:
                raise ValueError("Codex 提前关闭了 app-server")
            response = json.loads(line)
            if "id" not in response:
                continue
            if "error" in response:
                raise ValueError("Codex 拒绝读取 Skill 或配置")
            responses[response["id"]] = response["result"]
        return [responses[i] for i in range(1, len(requests) + 1)]
    except queue.Empty as error:
        raise ValueError("读取 Codex Skill 超时") from error
    finally:
        # npm 入口会启动子进程。先关闭输入，让 app-server 正常退出。
        with contextlib.suppress(OSError):
            process.stdin.close()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        reader.join(timeout=3)
        process.stdout.close()


def key(path):
    return os.path.normcase(str(Path(path).resolve()))


def inspect(cwd, options=()):
    config, loaded = rpc(cwd, [
        ("config/read", {"cwd": str(cwd), "includeLayers": True}),
        ("skills/list", {"cwds": [str(cwd)], "forceReload": True}),
    ], options)
    paths = [{**skill, "key": key(skill["path"])} for group in loaded["data"] for skill in group["skills"]]
    if any(group.get("errors") for group in loaded["data"]):
        print("Codex 报告部分 Skill 无法读取，可运行 codex 查看宿主诊断。", file=sys.stderr)
    return config, paths


def launch_options(config, paths, managed, selected):
    # 保留有效配置和各层已有规则，再对 Inventory 自己的路径追加限制。
    rules = {}
    for layer in reversed(config.get("layers") or []):
        if layer.get("disabledReason"):
            continue
        for rule in layer["config"].get("skills", {}).get("config", []):
            rules[key(rule["path"])] = {"path": rule["path"], "enabled": rule["enabled"]}
    for rule in (config["config"].get("skills") or {}).get("config", []):
        rules[key(rule["path"])] = {"path": rule["path"], "enabled": rule["enabled"]}
    manual_names = {skill["name"] for skill in paths if skill["key"] not in managed and skill["enabled"]}
    choices = [skill for skill in paths if skill["key"] in selected]
    duplicates = {skill["name"] for skill in choices
                  if sum(other["name"] == skill["name"] for other in choices) > 1}
    conflicts = []
    for skill in paths:
        path_key = skill["key"]
        if path_key not in managed:
            if not skill["enabled"] and path_key not in rules:
                rules[path_key] = {"path": skill["path"], "enabled": False}
            continue
        conflict = skill["name"] in manual_names or skill["name"] in duplicates
        if conflict and path_key in selected:
            conflicts.append(skill["name"])
        if path_key not in selected or conflict:
            rules[path_key] = {"path": skill["path"], "enabled": False}
    entries = ", ".join('{path = ' + json.dumps(rule["path"], ensure_ascii=False)
                        + ', enabled = ' + str(rule["enabled"]).lower() + '}'
                        for rule in rules.values())
    return ["-c", "skills.config=[" + entries + "]"], sorted(set(conflicts))
