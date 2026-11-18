"""Windows 桌面客户端，后台任务通过现有客户端接口执行。"""

import argparse
import contextlib
from io import StringIO
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from . import cli, state, sync


class Window:
    def __init__(self, root, projects):
        self.root = root
        self.projects = list(dict.fromkeys(str(path.resolve()) for path in projects))
        self.results = queue.Queue()
        self.busy = False
        self.catalog = {}
        self.data = state.state()
        self.scope = tk.StringVar(value="用户级")
        self.mode = tk.StringVar(value="跟随最新版")
        self.version = tk.StringVar()
        self.notice = tk.StringVar()
        self.health = tk.StringVar()
        self.server = tk.StringVar(value=self.data.get("server", "http://127.0.0.1:8787"))
        self.interval = tk.StringVar(value=str(self.data["interval"]))
        self.token = tk.StringVar()
        root.title("Skill Inventory 客户端")
        root.geometry("940x720")
        root.minsize(780, 630)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        binding = ttk.LabelFrame(root, text="设备绑定", padding=12)
        binding.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        binding.columnconfigure(1, weight=1)
        for row, (label, variable, hide) in enumerate([
            ("服务端", self.server, ""), ("设备令牌", self.token, "•"),
            ("同步间隔（秒）", self.interval, ""),
        ]):
            ttk.Label(binding, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=3)
            ttk.Entry(binding, textvariable=variable, show=hide).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(binding, text="绑定设备", command=self.bind).grid(row=1, column=2, padx=(10, 0))

        actions = ttk.Frame(root, padding=(16, 4))
        actions.grid(row=1, column=0, sticky="ew")
        for label, callback in [
            ("启动后台", lambda: self.job(lambda: cli.control("start"))),
            ("停止后台", lambda: self.job(lambda: cli.control("stop"))),
            ("立即同步", lambda: self.job(self.synchronize)),
            ("刷新 Skill 库", lambda: self.job(self.refresh_catalog, self.set_catalog)),
        ]:
            ttk.Button(actions, text=label, command=callback).pack(side="left", padx=(0, 8))
        ttk.Label(root, textvariable=self.health).grid(row=2, column=0, sticky="w", padx=16, pady=6)

        skills = ttk.LabelFrame(root, text="Skill 与项目配置", padding=10)
        skills.grid(row=3, column=0, sticky="nsew", padx=16, pady=4)
        skills.columnconfigure(0, weight=1)
        skills.rowconfigure(1, weight=1)
        picker = ttk.Frame(skills)
        picker.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(picker, text="应用范围").pack(side="left", padx=(0, 8))
        self.scopes = ttk.Combobox(picker, textvariable=self.scope, state="readonly", width=54)
        self.scopes.pack(side="left", fill="x", expand=True)
        self.scopes.bind("<<ComboboxSelected>>", lambda _: self.render_skills())
        ttk.Button(picker, text="选择项目目录", command=self.pick_project).pack(side="left", padx=(8, 0))
        columns = ("name", "available", "rule", "installed")
        self.tree = ttk.Treeview(skills, columns=columns, selectmode="browse")
        for column, label, width in [
            ("#0", "Slug", 175), ("name", "Skill 名称", 185), ("available", "可用最新版", 105),
            ("rule", "当前规则", 145), ("installed", "已同步版本", 110),
        ]:
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=70)
        self.tree.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(skills, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self.show_rule)

        edit = ttk.Frame(skills)
        edit.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.modes = ttk.Combobox(edit, textvariable=self.mode, state="readonly", width=15)
        self.modes.pack(side="left")
        self.versions = ttk.Combobox(edit, textvariable=self.version, width=11)
        self.versions.pack(side="left", padx=6)
        for label, callback in [
            ("查看可选版本", self.list_versions), ("保存规则", self.save_rule),
            ("检查 Codex 启用", self.inspect), ("启动 Codex", self.launch_codex),
        ]:
            ttk.Button(edit, text=label, command=callback).pack(side="left", padx=(0, 5))

        result = ttk.LabelFrame(root, text="操作结果与同步诊断", padding=8)
        result.grid(row=4, column=0, sticky="ew", padx=16, pady=(8, 12))
        ttk.Label(result, textvariable=self.notice).pack(anchor="w")
        self.output = tk.Text(result, height=6, wrap="word", state="disabled", font=("Segoe UI", 10))
        self.output.pack(fill="x", pady=(4, 0))
        self.render_status()
        self.render_skills()
        root.after(100, self.poll)
        root.after(2000, self.tick)
        if self.data.get("server"):
            self.job(self.refresh_catalog, self.set_catalog)

    def job(self, action, finish=None):
        if self.busy:
            self.notice.set("正在执行上一项操作，请稍候")
            return
        self.busy = True
        self.notice.set("正在处理…")

        def execute():
            output = StringIO()
            try:
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    value = action()
                self.results.put((finish, value, output.getvalue(), None))
            except Exception as error:
                self.results.put((None, None, output.getvalue(), str(error)))

        threading.Thread(target=execute, daemon=True).start()

    def poll(self):
        try:
            finish, value, output, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.notice.set(error or "操作完成")
            self.render_status()
            if finish is not None:
                finish(value)
            if output or error:
                self.show_output("\n".join(part for part in (output.strip(), error) if part))
        self.root.after(100, self.poll)

    def tick(self):
        if not self.busy:
            self.render_status(quiet=True)
        self.root.after(2000, self.tick)

    def render_status(self, quiet=False):
        current = state.state()
        running = cli.running()
        account = current.get("account", {}).get("username", "未绑定")
        checked = current.get("lastChecked", "暂无")
        connected = current.get("lastConnected", "暂无")
        self.health.set(f"账号 {account}    后台同步 {'运行中' if running else '已停止'}    "
                        f"最近检查 {checked}    最近连通 {connected}")
        if not quiet or current != self.data:
            self.show_output("\n".join(current["issues"]) or "没有同步问题")
            if current.get("account") != self.data.get("account") or current.get("server") != self.data.get("server"):
                self.catalog = {}
            update_skills = any(current[key] != self.data[key] for key in ("user", "projects", "resolved"))
            self.data = current
            if update_skills:
                self.render_skills()

    def show_output(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def bind(self):
        if self.busy:
            self.notice.set("正在执行上一项操作，请稍候")
            return
        token = self.token.get().strip()
        self.token.set("")
        server, interval = self.server.get(), self.interval.get()

        def apply():
            with state.lock("state"):
                cli.bind(state.state(), server, int(interval), token)
            return self.refresh_catalog()

        self.job(apply, self.set_catalog)

    def synchronize(self):
        ok, _ = cli.run_sync()
        if ok:
            print("同步完成")
        else:
            raise ValueError("同步未完成，请查看诊断")

    def api(self):
        server = state.state().get("server")
        if not server:
            raise ValueError("请先绑定设备")
        return sync.Api(server, state.get_token())

    def refresh_catalog(self):
        return {skill["slug"]: skill for skill in self.api().get("/skills")}

    def set_catalog(self, catalog):
        self.catalog = catalog
        self.render_skills()

    def project(self):
        scope = self.scope.get()
        return None if scope == "用户级" else Path(scope)

    def pick_project(self):
        path = filedialog.askdirectory(parent=self.root, mustexist=True)
        if path:
            project = str(Path(path).resolve())
            if project not in self.projects:
                self.projects.append(project)
            self.scope.set(project)
            self.render_skills()

    def rules(self):
        project = self.project()
        return self.data["user"] if project is None else self.data["projects"].get(str(project), {})

    def render_skills(self):
        self.scopes.configure(values=["用户级", *dict.fromkeys([*self.projects, *self.data["projects"]])])
        old = self.tree.selection()
        if self.tree.get_children():
            self.tree.delete(*self.tree.get_children())
        project = self.project()
        effective = self.data["user"] if project is None else sync.selected(self.data, project)
        rules = self.rules()
        for slug in sorted(self.catalog.keys() | effective.keys() | rules.keys() | self.data["user"].keys()):
            skill = self.catalog.get(slug, {})
            choice = rules.get(slug)
            labels = {"latest": "跟随最新版", "off": "停用", None: "未启用" if project is None else "继承"}
            rule = labels.get(choice, f"固定 {choice}")
            active = effective.get(slug)
            installed = self.data["resolved"].get(sync.selector(slug, active), "") if active else ""
            self.tree.insert("", "end", iid=slug, text=slug,
                             values=(skill.get("name", ""), skill.get("version", ""), rule, installed))
        if old and self.tree.exists(old[0]):
            self.tree.selection_set(old[0])
        self.show_rule()

    def show_rule(self, _event=None):
        modes = ["跟随最新版", "固定版本", "停用"]
        if self.project() is not None:
            modes.append("继承")
        self.modes.configure(values=modes)
        self.versions.configure(values=[])
        selected = self.tree.selection()
        rule = self.rules().get(selected[0]) if selected else None
        label = {"latest": "跟随最新版", "off": "停用", None: "继承" if self.project() else "停用"}
        self.mode.set(label.get(rule, "固定版本"))
        self.version.set(rule if rule not in label else "")

    def list_versions(self):
        selected = self.tree.selection()
        if not selected:
            self.notice.set("请先选择一个 Skill")
            return
        slug = selected[0]

        def finish(versions):
            if self.tree.selection() == (slug,):
                self.versions.configure(values=versions)
                self.show_output("可选版本：" + "、".join(versions))

        self.job(lambda: [item["version"] for item in self.api().get(f"/skills/{slug}/versions")], finish)

    def save_rule(self):
        selected = self.tree.selection()
        if not selected:
            self.notice.set("请先选择一个 Skill")
            return
        mode = self.mode.get()
        action = {"停用": "disable", "继承": "inherit"}.get(mode, "enable")
        args = argparse.Namespace(slug=selected[0], action=action, project=self.project(),
                                  version=self.version.get().strip() if mode == "固定版本" else "latest")

        def apply():
            with state.lock("state"):
                cli.select(state.state(), args)
            print("规则已保存，等待后台同步或点击立即同步。")

        self.job(apply)

    def inspect(self):
        project = self.project()
        if project is None:
            self.notice.set("请先选择项目目录")
            return

        def check():
            _, conflicts, rows = cli.discover(project)
            warnings = "\n".join(f"同名冲突：{name}" for name in conflicts)
            active = [
                f"{item['name']}    {Path(item['path']).parent.name.rsplit('--', 1)[-1]}"
                for item in rows if item["enabled"]
            ]
            return "\n".join([*(active or ["没有启用的受管 Skill"]), warnings]).strip()

        self.job(check, self.show_output)

    def launch_codex(self):
        project = self.project()
        if project is None:
            self.notice.set("请先选择项目目录")
            return
        self.job(lambda: subprocess.Popen(
            [cli.console_python(), "-X", "utf8", "-m", "skill_inventory.cli", "codex"],
            cwd=project, creationflags=subprocess.CREATE_NEW_CONSOLE,
        ))


def main():
    parser = argparse.ArgumentParser(description="Skill Inventory Windows 桌面客户端")
    parser.add_argument("--project", action="append", default=[], type=Path, help="预置项目目录")
    args = parser.parse_args()
    root = tk.Tk()
    Window(root, args.project)
    root.mainloop()


if __name__ == "__main__":
    main()
