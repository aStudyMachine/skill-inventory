"""便携 EXE 的 Python 入口，只使用演示目录中的客户端配置。"""

import contextlib
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox

import demo


def main():
    root = tk.Tk()
    root.withdraw()
    try:
        pointer = demo.BUNDLE / "demo-data/current"
        if not pointer.is_file():
            raise ValueError("请先打开 Start-Demo.cmd，完成演示初始化。")
        lab = demo.current_lab(pointer)
        if not all((lab / "projects" / name).is_dir() for name in demo.PROJECTS):
            raise ValueError("演示项目还未初始化，请在 Start-Demo.cmd 启动完成后重试。")
        demo.process_env(lab)
        from skill_inventory.gui import Window

        with (lab / "desktop.log").open("a", encoding="utf-8") as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                Window(root, [lab / "projects" / name for name in demo.PROJECTS])
                root.deiconify()
                root.mainloop()
        return 0
    except Exception as error:
        messagebox.showerror("Skill Inventory 客户端", str(error), parent=root)
        root.destroy()
        return 1


if __name__ == "__main__":
    sys.exit(main())
