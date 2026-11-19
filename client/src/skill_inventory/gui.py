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
from tkinter import filedialog, messagebox, ttk

from . import cli, state, sync


class Window:
    def __init__(self, root, projects, *, codex_controls=True, demo_login=None):
        self.root = root
        root.withdraw()
        self.login_dialog = None
        self.authenticated = None
        self.demo_login = demo_login
        self.results = queue.Queue()
        self.busy = False
        self.data = state.state()
        if projects:
            with state.lock("state"):
                self.data = state.state()
                for project in projects:
                    cli.set_target(self.data, "add-project", project)
        self.scope = tk.StringVar(value="用户级")
        self.mode = tk.StringVar(value="跟随最新版")
        self.version = tk.StringVar()
        self.notice = tk.StringVar()
        self.health = tk.StringVar()
        self.destination = tk.StringVar()
        self.server = tk.StringVar(value=self.data.get("server", "http://127.0.0.1:8787"))
        self.interval = tk.StringVar(value=str(self.data["interval"]))
        self.username = tk.StringVar(value=self.data.get("account", {}).get("username", ""))
        self.password = tk.StringVar()
        self.remember = tk.BooleanVar()
        self.server.trace_add("write", self.server_changed)
        root.title("Skill Inventory 客户端")
        root.geometry("940x720")
        root.minsize(780, 630)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        actions = ttk.Frame(root, padding=(16, 12, 16, 4))
        actions.grid(row=1, column=0, sticky="ew")
        for label, callback in [
            ("启动后台", lambda: self.job(lambda: cli.control("start"))),
            ("停止后台", lambda: self.job(lambda: cli.control("stop"))),
            ("立即同步", lambda: self.job(self.synchronize)),
            ("刷新 Skill 库", lambda: self.job(self.refresh_catalog)),
            ("退出登录", self.logout),
        ]:
            ttk.Button(actions, text=label, command=callback).pack(side="left", padx=(0, 8))
        options = ttk.Frame(actions)
        options.pack(side="right")
        ttk.Label(options, text="同步间隔（秒）").pack(side="left", padx=(0, 6))
        interval_entry = ttk.Entry(options, textvariable=self.interval, width=7)
        interval_entry.pack(side="left", padx=(0, 6))
        interval_entry.bind("<Return>", lambda _: self.save_interval())
        ttk.Button(options, text="保存", command=self.save_interval).pack(side="left")
        ttk.Label(root, textvariable=self.health).grid(row=2, column=0, sticky="w", padx=16, pady=6)

        skills = ttk.LabelFrame(root, text="Skill 与项目配置", padding=10)
        skills.grid(row=3, column=0, sticky="nsew", padx=16, pady=4)
        skills.columnconfigure(0, weight=1)
        skills.rowconfigure(2, weight=1)
        picker = ttk.Frame(skills)
        picker.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(picker, text="应用范围").pack(side="left", padx=(0, 8))
        self.scopes = ttk.Combobox(picker, textvariable=self.scope, state="readonly", width=54)
        self.scopes.pack(side="left", fill="x", expand=True)
        self.scopes.bind("<<ComboboxSelected>>", lambda _: self.render_skills())
        ttk.Button(picker, text="用户级目录", command=lambda: self.pick_target("set-user-root")).pack(side="left", padx=(8, 0))
        ttk.Button(picker, text="选择项目目录", command=self.pick_project).pack(side="left", padx=(8, 0))
        ttk.Button(picker, text="移除项目", command=self.remove_project).pack(side="left", padx=(8, 0))
        ttk.Label(skills, textvariable=self.destination).grid(row=1, column=0, sticky="w", pady=(0, 6))
        columns = ("enabled", "description", "installed", "available", "rule")
        self.tree = ttk.Treeview(skills, columns=columns, selectmode="browse")
        for column, label, width in [
            ("#0", "Skill 名称", 175), ("enabled", "启用", 55), ("description", "描述", 165),
            ("installed", "本地版本", 110), ("available", "服务器版本", 105), ("rule", "当前规则", 145),
        ]:
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=70)
        self.tree.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(skills, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self.show_rule)
        self.tree.bind("<Button-1>", self.click_enabled)
        self.tree.bind("<space>", self.toggle_selected)

        edit = ttk.Frame(skills)
        edit.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.modes = ttk.Combobox(edit, textvariable=self.mode, state="readonly", width=15)
        self.modes.pack(side="left")
        self.versions = ttk.Combobox(edit, textvariable=self.version, width=11)
        self.versions.pack(side="left", padx=6)
        buttons = [("查看可选版本", self.list_versions), ("保存规则", self.save_rule)]
        if codex_controls:
            buttons.extend([("检查 Codex 启用", self.inspect), ("启动 Codex", self.launch_codex)])
        for label, callback in buttons:
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
        if self.authenticated:
            self.job(self.refresh_catalog)

    def show_login(self):
        self.root.withdraw()
        self.username.set("")
        self.password.set("")
        server = self.server.get()
        saved = state.remembered_login(server)
        self.remember.set(saved is not None)
        demo_credentials = self.demo_login[1:] if self.demo_login and self.demo_login[0] == server else None
        if credentials := saved or demo_credentials:
            username, secret = credentials
            self.username.set(username)
            self.password.set(secret)
        self.demo_login = None
        dialog = self.login_dialog = tk.Toplevel(self.root)
        dialog.title("登录 Skill Inventory")
        dialog.resizable(False, False)
        dialog.protocol("WM_DELETE_WINDOW", self.root.destroy)
        dialog.bind("<Return>", lambda _: self.login())
        form = ttk.Frame(dialog, padding=20)
        form.pack(fill="both", expand=True)
        for row, (label, variable, hide) in enumerate([
            ("服务端", self.server, ""), ("账号", self.username, ""), ("密码", self.password, "•"),
        ]):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            entry = ttk.Entry(form, textvariable=variable, show=hide, width=42)
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            if variable is self.username:
                account_entry = entry
        ttk.Checkbutton(form, text="记住账号和密码", variable=self.remember).grid(
            row=3, column=1, sticky="w", pady=(4, 0))
        ttk.Label(form, textvariable=self.notice, wraplength=365).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(8, 4))
        ttk.Button(form, text="登录", command=self.login).grid(row=5, column=1, sticky="e")
        account_entry.focus_set()

    def server_changed(self, *_):
        self.password.set("")
        self.remember.set(False)

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
        authenticated = bool(current.get("account"))
        if authenticated:
            try:
                state.get_session()
            except state.LoginRequired:
                authenticated = False
        if authenticated != self.authenticated:
            self.authenticated = authenticated
            if authenticated:
                if self.login_dialog is not None:
                    self.login_dialog.destroy()
                    self.login_dialog = None
                self.root.deiconify()
            else:
                self.show_login()
        running = cli.running()
        account = current.get("account", {}).get("username", "未登录")
        checked = current.get("lastChecked", "暂无")
        connected = current.get("lastConnected", "暂无")
        self.health.set(f"账号 {account}    后台同步 {'运行中' if running else '已停止'}    "
                        f"最近检查 {checked}    最近连通 {connected}")
        if not quiet or current != self.data:
            self.show_output("\n".join(current["issues"]) or "没有同步问题")
            identity_changed = any(current.get(key) != self.data.get(key) for key in ("account", "server"))
            update_skills = any(current.get(key) != self.data.get(key)
                                for key in ("catalog", "user", "projects", "placements", "userRoot"))
            if current["interval"] != self.data["interval"]:
                self.interval.set(str(current["interval"]))
            self.data = current
            if identity_changed or update_skills:
                self.render_skills()

    def show_output(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def login(self):
        if self.busy:
            self.notice.set("正在执行上一项操作，请稍候")
            return
        username, password = self.username.get().strip(), self.password.get()
        self.password.set("")
        server, remember = self.server.get(), self.remember.get()

        def apply():
            with state.lock("state"):
                data = state.state()
                cli.login(data, server, username, password, data["interval"])
                if remember:
                    state.remember_login(data["server"], username, password)
                else:
                    state.forget_login()
            self.refresh_catalog()

        self.job(apply)

    def save_interval(self):
        try:
            interval = cli.validate_interval(int(self.interval.get()))
        except ValueError:
            self.notice.set("同步间隔须为 5 至 86400 秒的整数")
            return

        def apply():
            with state.lock("state"):
                data = state.state()
                data["interval"] = interval
                state.save(data)

        self.job(apply, lambda _: self.interval.set(str(interval)))

    def logout(self):
        def apply():
            with state.lock("state"):
                cli.logout(state.state())

        self.job(apply)

    def synchronize(self):
        ok, _ = cli.run_sync()
        if ok:
            print("同步完成")
        else:
            raise ValueError("同步未完成，请查看诊断")

    def api(self):
        server = state.state().get("server")
        if not server:
            raise ValueError("请先登录")
        return sync.Api(server, state.get_session())

    def refresh_catalog(self):
        with state.lock("state"):
            data = state.state()
            data["catalog"] = {skill["name"]: skill for skill in self.api().get("/skills")}
            state.save(data)

    def project(self):
        scope = self.scope.get()
        return None if scope == "用户级" else Path(scope)

    def pick_project(self):
        self.pick_target("add-project")

    def remove_project(self):
        project = self.project()
        if project is None:
            self.notice.set("请先选择要移除的项目")
            return
        if messagebox.askyesno("移除项目", f"移除 {project} 的登记和规则？\n下次同步会清理其中的受管文件。",
                               parent=self.root):
            self.save_target("remove-project", project, "用户级")

    def pick_target(self, action):
        initial = sync.user_root(self.data) if action == "set-user-root" else self.project()
        if initial is None or not initial.is_dir():
            initial = Path.home()
        path = filedialog.askdirectory(parent=self.root, mustexist=True,
                                       initialdir=initial if initial.is_dir() else Path.cwd())
        if path:
            root = Path(path).resolve()
            self.save_target(action, root, "用户级" if action == "set-user-root" else str(root))

    def save_target(self, action, root, scope):
        def apply():
            with state.lock("state"):
                cli.set_target(state.state(), action, root)
            print("同步目录已保存。可点击立即同步。")

        def finish(_):
            self.scope.set(scope)
            self.render_skills()

        self.job(apply, finish)

    def rules(self):
        project = self.project()
        return self.data["user"] if project is None else self.data["projects"].get(str(project), {})

    def render_skills(self):
        self.scopes.configure(values=["用户级", *self.data["projects"]])
        if self.project() is not None and self.scope.get() not in self.data["projects"]:
            self.scope.set("用户级")
        old = self.tree.selection()
        if self.tree.get_children():
            self.tree.delete(*self.tree.get_children())
        project = self.project()
        target = project or sync.user_root(self.data)
        self.destination.set(f"同步到 {sync.installation_directory(target)}")
        rules = self.rules()
        catalog = self.data.get("catalog")
        for slug in sorted(rules if catalog is None else catalog):
            skill = catalog[slug] if catalog is not None else {}
            choice = rules.get(slug)
            labels = {"latest": "跟随最新版", "off": "未启用", None: "未启用"}
            rule = labels.get(choice, f"固定 {choice}")
            active = choice not in (None, "off")
            installed = (sync.version_at(self.data, target, sync.selector(slug, choice)) or "") if active else ""
            self.tree.insert("", "end", iid=slug, text=slug,
                             values=("☑" if active else "☐", skill.get("description", ""),
                                     installed, skill.get("version", ""), rule))
        if old and self.tree.exists(old[0]):
            self.tree.selection_set(old[0])
        self.show_rule()

    def show_rule(self, _event=None):
        self.modes.configure(values=["跟随最新版", "固定版本", "停用"])
        self.versions.configure(values=[])
        selected = self.tree.selection()
        rule = self.rules().get(selected[0]) if selected else None
        label = {"latest": "跟随最新版", "off": "停用", None: "停用"}
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
        self.update_rule(selected[0], "disable" if mode == "停用" else "enable",
                         self.version.get().strip() if mode == "固定版本" else "latest")

    def click_enabled(self, event):
        slug = self.tree.identify_row(event.y)
        if slug and self.tree.identify_column(event.x) == "#1":
            self.tree.selection_set(slug)
            self.tree.focus(slug)
            return self.toggle_selected()

    def toggle_selected(self, _event=None):
        if selected := self.tree.selection():
            slug = selected[0]
            self.update_rule(slug, "enable" if self.rules().get(slug) in (None, "off") else "disable", "latest")
        return "break"

    def update_rule(self, slug, action, version):
        args = argparse.Namespace(name=slug, action=action, project=self.project(), version=version)

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
