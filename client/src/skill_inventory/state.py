"""保存客户端配置和受管理文件包，凭据由 Windows 保管。"""

from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
import msvcrt
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import time
import zipfile

SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
VERSION = re.compile(r"(?:0|[1-9][0-9]{0,8})(?:\.(?:0|[1-9][0-9]{0,8})){2}")
DEVICE_NAME = re.compile(r"(?i)(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³]|CONIN\$|CONOUT\$)(\..*)?")
MARKER = ".skill-inventory.json"
ROOT = Path(os.environ.get("SKILL_INVENTORY_STATE_DIR") or Path(os.environ["LOCALAPPDATA"]) / "SkillInventory")
CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()
PACKAGES = (ROOT / "legacy-packages" if "SKILL_INVENTORY_STATE_DIR" in os.environ
            else CODEX_HOME / "skills" / "skill-inventory-managed")


def write_json(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as output:
        temporary = Path(output.name)
        json.dump(data, output, ensure_ascii=False, indent=2)
    try:
        # Windows 读者或文件扫描器可能短暂拒绝替换，保留原子写入方式并重试。
        for delay in (0.02, 0.05, 0.1, 0.2, None):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if delay is None:
                    raise
                time.sleep(delay)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def lock(name, wait=True):
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / (name + ".lock")).open("a+b") as file:
        file.seek(0)
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK, 1)
        except OSError:
            raise ValueError("同步或后台进程仍在运行") from None
        try:
            yield
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)


def state():
    path = ROOT / "state.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"user": {}, "projects": {}, "resolved": {}, "interval": 300, "issues": []}


def save(data):
    write_json(ROOT / "state.json", data)


def vault():
    from keyring.backends.Windows import WinVaultKeyring

    return WinVaultKeyring(), "Skill Inventory " + hashlib.sha256(
        os.fsencode(os.path.normcase(str(ROOT.resolve())))).hexdigest()[:20]


class LoginRequired(ValueError):
    """客户端没有可用的本地登录。"""


def get_session():
    backend, service = vault()
    session = backend.get_password(service, "session")
    if not session:
        raise LoginRequired("请先登录 Skill Inventory")
    return session


def save_session(session):
    backend, service = vault()
    backend.set_password(service, "session", session)
    clear_legacy_session()


def clear_session():
    backend, service = vault()
    if backend.get_password(service, "session"):
        backend.delete_password(service, "session")
    clear_legacy_session()


def remembered_login(server):
    backend, service = vault()
    saved = backend.get_password(service, "remembered-login")
    if saved:
        origin, username, secret = json.loads(saved)
        if origin == server:
            return username, secret
    return None


def remember_login(server, username, secret):
    backend, service = vault()
    backend.set_password(service, "remembered-login", json.dumps([server, username, secret]))


def forget_login():
    backend, service = vault()
    if backend.get_password(service, "remembered-login"):
        backend.delete_password(service, "remembered-login")


def clear_legacy_session():
    backend, service = vault()
    if backend.get_password(service, "device"):
        backend.delete_password(service, "device")


def name_valid(name):
    return bool(SKILL_NAME.fullmatch(name) and len(name) <= 64 and not DEVICE_NAME.fullmatch(name))


def skills_dir(root):
    return Path(root) / ".agents" / "skills"


def package_path(slug, version, directory=None):
    if not name_valid(slug) or not VERSION.fullmatch(version):
        raise ValueError("收到无效的 Skill 标识或版本号")
    return (directory if directory is not None else PACKAGES) / (slug + "--" + version)


def is_link(path):
    return path.is_symlink() or path.is_junction()


def unsafe_directory(directory):
    return (directory.resolve() != directory or is_link(directory.parent)
            or is_link(directory))


def owned(path):
    if unsafe_directory(path.parent) or is_link(path) or not path.is_dir():
        return False
    marker = path / MARKER
    if is_link(marker) or not marker.is_file():
        return False
    try:
        record = json.loads(marker.read_text(encoding="utf-8"))
        name = record["name"] if "name" in record else record["slug"]
        return (package_path(name, record["version"], path.parent) == path
                and record["owner"] == str(ROOT.resolve()))
    except (ValueError, KeyError, OSError, TypeError):
        return False


def installed(directory=None):
    directory = directory if directory is not None else PACKAGES
    if unsafe_directory(directory):
        raise ValueError(f"安装位置是链接，已保留原目录 {directory}")
    if not directory.is_dir():
        return []
    return [path for path in directory.iterdir() if owned(path)]


def extract(archive, folder):
    with zipfile.ZipFile(BytesIO(archive)) as package:
        entries = package.infolist()
        if not 1 <= len(entries) <= 512 or sum(item.file_size for item in entries) > 16 * 1024 * 1024:
            raise ValueError("ZIP 超过包限制")
        if not any(item.filename == "SKILL.md" for item in entries):
            raise ValueError("ZIP 缺少根目录 SKILL.md")
        seen = set()
        for item in entries:
            name = item.orig_filename
            parts = name.rstrip("/").split("/")
            if (len(name) > 220 or stat.S_ISLNK(item.external_attr >> 16)
                    or any(not part or part.endswith((".", " ")) or DEVICE_NAME.fullmatch(part)
                           or any(ord(c) < 32 or c in '\\:*?"<>|' for c in part) for part in parts)
                    or parts[0].casefold() == MARKER):
                raise ValueError("ZIP 包含不安全的文件路径")
            target = folder.joinpath(*PurePosixPath(*parts).parts)
            relative = "/".join(parts).casefold()
            if relative in seen:
                raise ValueError("ZIP 包含重复路径")
            seen.add(relative)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(item) as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination)
        (folder / "SKILL.md").read_text(encoding="utf-8")


def install(slug, version, archive, directory=None):
    destination = package_path(slug, version, directory)
    directory = destination.parent
    if unsafe_directory(directory):
        raise ValueError(f"安装位置是链接，已保留原目录 {directory}")
    if destination.exists() or is_link(destination):
        if owned(destination):
            return destination
        raise ValueError(f"安装冲突，已保留手动文件 {destination}")
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".skill-inventory-", dir=directory.parent) as temporary:
        folder = Path(temporary) / "package"
        folder.mkdir()
        extract(archive, folder)
        write_json(folder / MARKER, {"name": slug, "version": version, "owner": str(ROOT.resolve())})
        folder.rename(destination)
    return destination


def retire(path):
    if owned(path):
        with tempfile.TemporaryDirectory(prefix=".skill-inventory-retired-", dir=path.parent.parent) as temporary:
            path.rename(Path(temporary) / "package")


def timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
