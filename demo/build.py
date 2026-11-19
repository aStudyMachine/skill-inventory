"""在开发机构建 Windows x64 便携演示包。"""

import argparse
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_NAME = "Skill-Inventory-Demo"
ZIP_NAME = BUNDLE_NAME + "-Windows-x64"
STAMP = r"(?:-\d{8}-\d{6}-\d{6})?"
ARCHIVES = {
    "temurin.zip": "2332c0b4cff6bed722da3567c91d5e47568bcba863fa4945d0a8d6fc76158628",
    "python.zip": "d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15",
}


def execute(program, *args):
    resolved = shutil.which(program)
    if not resolved:
        raise SystemExit(f"未找到开发工具 {program}")
    subprocess.run([resolved, *map(str, args)], cwd=ROOT, check=True)


def digest(path):
    with path.open("rb") as contents:
        return hashlib.file_digest(contents, "sha256").hexdigest()


def copy_source(destination):
    # 分发内的清单让解压后的源码可以独立重建，不依赖原仓库的 .git。
    manifest = ROOT / "SOURCE-FILES.txt"
    if manifest.is_file():
        names = manifest.read_text(encoding="utf-8").splitlines()
    else:
        names = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
        ).decode("utf-8").split("\0")
    copied = []
    for name in sorted(set(names) - {"", manifest.name}):
        path = ROOT / name
        if not path.resolve().is_relative_to(ROOT):
            raise SystemExit(f"源码文件超出源码目录：{name}")
        if path.is_file():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied.append(name)
        elif manifest.is_file():
            raise SystemExit(f"源码清单中的文件不存在：{name}")
    (destination / manifest.name).write_text("\n".join(copied) + "\n", encoding="utf-8")


def build(args):
    inputs = args.inputs.resolve(strict=True)
    output = args.output.resolve()
    for name, expected in ARCHIVES.items():
        if digest(inputs / name) != expected:
            raise SystemExit(f"{name} 的 SHA-256 不符")
    execute("mvn.cmd", "-B", "-f", "server/pom.xml", "clean", "package")
    execute("npm.cmd", "--prefix", "web", "ci", "--no-audit", "--no-fund")
    execute("npm.cmd", "--prefix", "web", "run", "build")
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "client/tests"],
                   cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT / "client/src")), check=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".demo-build-", dir=output) as staging:
        staging = Path(staging)
        bundle = staging / f"{BUNDLE_NAME}-{stamp}"
        target = staging / f"{ZIP_NAME}-{stamp}.zip"
        package(inputs, bundle, target)
        # 完整生成并计算校验值后才发布本轮产物，最后清理历史。
        published = set()
        for path in (bundle, target.with_suffix(".zip.sha256"), target):
            destination = output / path.name
            path.rename(destination)
            published.add(destination)
        clean_builds(output, published)
        print(output / target.name)


def clean_builds(output, published):
    for path in output.iterdir():
        if path in published or path.is_symlink() or path.is_junction() or path.resolve().parent != output:
            continue
        try:
            if path.is_file() and re.fullmatch(ZIP_NAME + STAMP + r"\.zip(?:\.sha256)?", path.name):
                path.unlink()
            elif path.is_dir() and re.fullmatch(BUNDLE_NAME + STAMP, path.name):
                if (path / "demo-data").exists():
                    print(f"保留含演示运行数据的目录：{path}", file=sys.stderr)
                elif (path / "Start-Demo.cmd").is_file() and (path / "app/skill-inventory.jar").is_file():
                    shutil.rmtree(path)
        except OSError as error:
            print(f"历史产物清理失败：{path}（{error}）", file=sys.stderr)


def package(inputs, bundle, target):
    runtime = bundle / "runtime"
    runtime.mkdir(parents=True)
    with ZipFile(inputs / "temurin.zip") as archive:
        archive.extractall(runtime)
    (runtime / "jdk-21.0.13+9-jre").rename(runtime / "java")
    python = runtime / "python"
    with ZipFile(inputs / "python.zip") as archive:
        archive.extractall(python)
    with (python / "python314._pth").open("a", encoding="ascii") as config:
        config.write("\n../python-libs\n../../source/client/src\n../../source/demo\n")
    # 官方完整安装中的 Tcl/Tk 9 运行库带内嵌脚本，便携 Python 需要单独携带。
    import tkinter

    if sys.version_info[:3] != (3, 14, 7) or tkinter.TkVersion != 9.0:
        raise SystemExit("请使用完整安装的 Windows x64 Python 3.14.7（含 Tcl/Tk 9）构建")
    installation = Path(sys.base_prefix)
    for name in ("_tkinter.pyd", "tcl90.dll", "tcl9tk90.dll", "zlib1.dll"):
        shutil.copy2(installation / "DLLs" / name, python)
    shutil.copytree(installation / "Lib/tkinter", python / "tkinter",
                    ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run([str(python / "python.exe"), "-c",
                    "import tkinter; root = tkinter.Tk(); root.withdraw(); root.destroy()"],
                   check=True)
    execute(sys.executable, "-m", "pip", "install", "--only-binary=:all:", "--no-deps",
            "--no-compile", "--target", runtime / "python-libs", "-r", "demo/requirements-windows.txt")

    app = bundle / "app"
    shutil.copytree(ROOT / "web/dist", app / "web")
    shutil.copy2(ROOT / "server/target/skill-inventory-0.3.0.jar", app / "skill-inventory.jar")
    copy_source(bundle / "source")
    shutil.copy2(ROOT / "demo/Start-Demo.cmd", bundle)
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64",
                    "/reference:System.Windows.Forms.dll",
                    f"/out:{bundle / 'Skill-Inventory-Client.exe'}",
                    str(ROOT / "demo/DesktopLauncher.cs")], check=True)
    (bundle / "bin").mkdir()
    shutil.copy2(ROOT / "demo/inventory.cmd", bundle / "bin")
    shutil.copy2(ROOT / "docs/demo-acceptance.md", bundle / "演示验收.md")

    with ZipFile(target, "x", ZIP_DEFLATED, compresslevel=3) as archive:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(bundle.parent).as_posix())
    target.with_suffix(".zip.sha256").write_text(f"{digest(target)}  {target.name}\n", encoding="ascii")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建 Skill Inventory Windows x64 演示包")
    parser.add_argument("--inputs", type=Path, required=True, help="两个经校验的上游运行时输入所在目录")
    parser.add_argument("--output", type=Path, required=True, help="固定输出目录，成功后清理其中的历史演示构建")
    build(parser.parse_args())
