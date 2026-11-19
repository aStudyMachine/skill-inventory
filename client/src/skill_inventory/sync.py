"""按账号权限和用户、项目的启用配置同步不可变发布版本。"""

from collections import defaultdict
from http import HTTPStatus
from http.client import HTTPException
from http.cookies import SimpleCookie
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zipfile import BadZipFile

from . import state


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        """登录信息只发给用户配置的服务端。"""
        return None


def server_address(value):
    parsed = urlsplit(value)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("请输入服务端地址，例如 http://127.0.0.1:8787")
    if parsed.path not in ("", "/"):
        raise ValueError("服务端地址不能包含路径")
    if parsed.scheme == "http":
        host = parsed.hostname
        if host == "localhost" or ipaddress.ip_address(host).is_loopback:
            return value.rstrip("/")
    raise ValueError("首版服务端地址须为 HTTP 回环地址")


class Api:
    def __init__(self, server, session=None):
        self.server = server_address(server)
        self.session = session
        self.opener = build_opener(ProxyHandler({}), NoRedirects())

    def login(self, username, password):
        account, headers = self.request("/client-session", method="POST",
                                        body={"username": username, "password": password})
        cookie = SimpleCookie(headers.get("Set-Cookie", ""))
        session = cookie["SkillInventoryClient"].value if "SkillInventoryClient" in cookie else ""
        if not re.fullmatch("[a-zA-Z0-9_-]{43}", session):
            raise ValueError("服务端未返回有效登录会话")
        return account, session

    def logout(self):
        self.request("/client-session", method="DELETE")

    def get(self, path, version=None, archive=False):
        query = "?" + urlencode({"version": version}) if version else ""
        data, _ = self.request(path + query, archive_version=version if archive else None)
        return data

    def request(self, path, *, method="GET", body=None, archive_version=None):
        headers = {"X-Skill-Inventory": "1"}
        if self.session:
            headers["Cookie"] = "SkillInventoryClient=" + self.session
        content = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            content = json.dumps(body).encode("utf-8")
        request = Request(self.server + "/api/v1" + path, data=content, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=8) as response:
                limit = 17 * 1024 * 1024
                data = response.read(limit + 1)
                if len(data) > limit:
                    raise ValueError("服务端返回的内容超过限制")
                if archive_version:
                    if response.headers.get("X-Skill-Version") != archive_version:
                        raise ValueError("下载响应版本与请求不一致")
                    return data, response.headers
                return json.loads(data) if data else None, response.headers
        except HTTPError as error:
            try:
                result = json.loads(error.read(8192))
                code, message = result["code"], result["message"]
            except (ValueError, KeyError, TypeError):
                code, message = None, f"服务端返回 HTTP {error.code}"
            raise ApiError(error.code, code, message) from None


def selector(slug, selection):
    return slug + "@" + selection


def project_for(projects, cwd):
    path = Path(cwd)
    return next((project for project in [path, *path.parents] if str(project) in projects), None)


def user_root(data):
    return Path(data.get("userRoot") or default_user_root())


def default_user_root():
    return Path.home().resolve() / ".skills-inv"


def installation_directory(root):
    root = Path(root)
    if os.environ.get("SKILL_INVENTORY_DEMO_LAYOUT") == "1" and root == default_user_root():
        return root / "skills"
    return state.skills_dir(root)


def scopes(data):
    return {str(user_root(data)): data["user"], **data["projects"]}


def selected(data, cwd):
    project = project_for(data["projects"], cwd)
    choices = data["user"] if project is None else data["projects"][str(project)]
    return {slug: selection for slug, selection in choices.items() if selection != "off"}


def wanted(data):
    requests = defaultdict(set)
    for root, choices in scopes(data).items():
        for slug, selection in choices.items():
            if selection != "off":
                requests[(slug, selection)].add(root)
    return requests


def legacy(data):
    return data.get("legacy", data["resolved"])


def version_at(data, root, key):
    return data.get("placements", {}).get(str(root), {}).get(key)


def desired_path(data, cwd, slug, selection):
    root = project_for(data["projects"], cwd) or user_root(data)
    key = selector(slug, selection)
    if version := version_at(data, root, key):
        directory = installation_directory(root)
        path = state.package_path(slug, version, directory)
        if directory != state.skills_dir(root) and not state.owned(path):
            old = state.package_path(slug, version, state.skills_dir(root))
            if state.owned(old):
                return old
        return path
    if version := legacy(data).get(key):
        return state.package_path(slug, version)
    return None


def revoke_all(data):
    data["resolved"] = {}
    data["legacy"] = {}
    data.pop("catalog", None)
    for versions in data.get("placements", {}).values():
        versions.clear()


def invalidate(data):
    """先停用已安装的受管版本，再移除本地凭据。"""
    revoke_all(data)
    data.pop("account", None)
    data.pop("lastConnected", None)
    state.save(data)
    try:
        state.clear_session()
    except OSError as error:
        data["issues"].append(f"无法清理本地登录凭据：{error}")


def sync(data):
    """服务端明确撤权时停用副本。临时失败保留最后一次成功安装。"""
    requests = wanted(data)
    data["lastChecked"] = state.timestamp()
    data["issues"] = []
    wanted_keys = {selector(*request) for request in requests}
    data["legacy"] = {key: version for key, version in legacy(data).items() if key in wanted_keys}
    placements = data.setdefault("placements", {})
    current_user = str(user_root(data))
    previous_users = set(data.get("previousUserRoots", ())) - scopes(data).keys()
    for root, versions in placements.items():
        for key in list(versions):
            slug, selection = key.split("@", 1)
            roots = requests.get((slug, selection), ())
            moving = root in previous_users and current_user in roots
            if root not in roots and not moving:
                versions.pop(key)
    try:
        session = state.get_session()
        api = Api(data["server"], session)
        account = api.get("/client-session")
        if account["id"] != data["account"]["id"] or account["username"] != data["account"]["username"]:
            raise state.LoginRequired("登录账号已变化，请重新登录")
        catalog = data["catalog"] = {item["name"]: item for item in api.get("/skills")}
        available = {name: skill["version"] for name, skill in catalog.items()}
        for slug in {item[0] for item in requests} - available.keys():
            clear_slug(data, slug)
        archives = {}
        for (slug, selection), roots in requests.items():
            sync_request(data, api, available, archives, slug, selection, roots)
        data["lastConnected"] = state.timestamp()
    except (ApiError, state.LoginRequired) as error:
        if isinstance(error, state.LoginRequired) or (
                error.status == HTTPStatus.UNAUTHORIZED and error.code == "client_login_required"):
            invalidate(data)
        data["issues"].append(str(error))
    except KeyError:
        data["issues"].append("服务端返回的数据无法识别")
    except (URLError, ValueError, OSError, HTTPException) as error:
        data["issues"].append(str(error))

    for root in previous_users:
        for key in placements.get(root, {}).keys() & placements.get(current_user, {}).keys():
            placements[root].pop(key)
    data["resolved"] = dict(data["legacy"])
    for versions in placements.values():
        data["resolved"].update(versions)
    state.save(data)
    cleanup(data)
    state.save(data)
    return not data["issues"]


def sync_request(data, api, available, archives, slug, selection, roots):
    key = selector(slug, selection)
    if slug not in available:
        problem(data, slug, selection, roots, "Skill 未发布、已归档或无读取权限")
        return
    version = available[slug] if selection == "latest" else selection
    try:
        for root in sorted(roots):
            directory = installation_directory(root)
            try:
                if not data.get("userRoot") and Path(root) == default_user_root():
                    Path(root).mkdir(exist_ok=True)
                if not Path(root).is_dir():
                    raise ValueError("配置的根目录暂时不可用")
                if not state.owned(state.package_path(slug, version, directory)):
                    if (slug, version) not in archives:
                        archives[(slug, version)] = api.get(f"/skills/{slug}/package", version, archive=True)
                    state.install(slug, version, archives[(slug, version)], directory)
                data["placements"].setdefault(root, {})[key] = version
            except (ValueError, OSError, HTTPException, BadZipFile) as error:
                problem(data, slug, selection, [root], error)
        if all(version_at(data, root, key) == version for root in roots):
            data["legacy"].pop(key, None)
    except ApiError as error:
        if error.status == HTTPStatus.UNAUTHORIZED and error.code == "client_login_required":
            raise
        if error.status == HTTPStatus.NOT_FOUND and error.code == "skill_unavailable":
            clear_slug(data, slug)
            available.pop(slug, None)
            data["catalog"].pop(slug, None)
        if error.status == HTTPStatus.NOT_FOUND and error.code == "version_unavailable":
            for versions in [data["legacy"], *data["placements"].values()]:
                versions.pop(key, None)
        problem(data, slug, selection, roots, error)


def installation_roots(data):
    roots = set(data.get("placements", {})) | {str(user_root(data)), *data["projects"]}
    directories = {installation_directory(root): Path(root) for root in sorted(roots)}
    for directory, root in list(directories.items()):
        old = state.skills_dir(root)
        if directory != old:
            directories[old] = root
    return directories


def directories(data):
    return [state.PACKAGES, *installation_roots(data)]


def cleanup(data):
    """先持久化启用状态，再清理旧文件。目录占用时下次同步重试。"""
    configured = {str(user_root(data)), *data["projects"]}
    roots = installation_roots(data)
    blocked = set()
    for directory, root in {state.PACKAGES: None, **roots}.items():
        versions = legacy(data) if root is None else data.get("placements", {}).get(str(root), {})
        active = {state.package_path(key.split("@", 1)[0], version, directory)
                  for key, version in versions.items()}
        if root is not None and directory != installation_directory(root):
            # 新位置安装失败时，先保留原来的受管副本。
            active = {path for path in active if not state.owned(installation_directory(root) / path.name)}
        try:
            installed = state.installed(directory)
        except (OSError, ValueError) as error:
            blocked.add(root)
            data["issues"].append(f"无法清理安装目录 {directory}：{error}")
            continue
        for path in installed:
            if path not in active:
                try:
                    state.retire(path)
                except (OSError, ValueError) as error:
                    blocked.add(root)
                    data["issues"].append(f"无法清理安装目录 {path}：{error}")
    for root in set(roots.values()) - blocked:
        if str(root) not in configured and not data["placements"].get(str(root)) and root.is_dir():
            data.get("placements", {}).pop(str(root), None)
    data["previousUserRoots"] = [
        root for root in data.get("previousUserRoots", []) if root in data.get("placements", {}) and root not in configured
    ]


def clear_slug(data, slug):
    for versions in [data["legacy"], *data["placements"].values()]:
        for key in list(versions):
            if key.startswith(slug + "@"):
                versions.pop(key)


def problem(data, slug, selection, scopes, error):
    data["issues"].append(f"{', '.join(sorted(scopes))} / {slug} ({selection})：{error}")
