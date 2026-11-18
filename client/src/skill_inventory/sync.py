"""按设备权限和用户、项目的启用配置同步不可变发布版本。"""

from collections import defaultdict
from http import HTTPStatus
from http.client import HTTPException
import ipaddress
import json
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
        """设备令牌只发给用户配置的服务端。"""
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
    def __init__(self, server, token):
        self.server = server
        self.token = token
        self.opener = build_opener(ProxyHandler({}), NoRedirects())

    def get(self, path, version=None, archive=False):
        query = "?" + urlencode({"version": version}) if version else ""
        request = Request(self.server + "/api/v1" + path + query,
                          headers={"Authorization": "Bearer " + self.token})
        try:
            with self.opener.open(request, timeout=8) as response:
                limit = 17 * 1024 * 1024
                data = response.read(limit + 1)
                if len(data) > limit:
                    raise ValueError("服务端返回的内容超过限制")
                if archive:
                    if response.headers.get("X-Skill-Version") != version:
                        raise ValueError("下载响应版本与请求不一致")
                    return data
                return json.loads(data)
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


def selected(data, cwd):
    project = project_for(data["projects"], cwd)
    choices = dict(data["user"])
    if project is not None:
        choices.update(data["projects"][str(project)])
    return {slug: selection for slug, selection in choices.items() if selection != "off"}


def wanted(data):
    requests = defaultdict(set)
    scopes = {"用户级": data["user"]}
    scopes.update({path: selected(data, path) for path in data["projects"] if Path(path).is_dir()})
    for scope, choices in scopes.items():
        for slug, selection in choices.items():
            requests[(slug, selection)].add(scope)
    return requests


def revoke_all(data):
    data["resolved"] = {}


def sync(data):
    """服务端明确撤权时停用副本。临时失败保留最后一次成功安装。"""
    requests = wanted(data)
    data["lastChecked"] = state.timestamp()
    data["issues"] = []
    wanted_keys = {selector(*request) for request in requests}
    data["resolved"] = {key: version for key, version in data["resolved"].items() if key in wanted_keys}
    try:
        api = Api(data["server"], state.get_token())
        account = api.get("/device")
        if account["id"] != data["account"]["id"] or account["username"] != data["account"]["username"]:
            revoke_all(data)
            raise ValueError("设备令牌所属账号已变化，请重新运行 configure")
        available = {item["slug"]: item["version"] for item in api.get("/skills")}
        for slug in {item[0] for item in requests} - available.keys():
            clear_slug(data, slug)
        for (slug, selection), scopes in requests.items():
            try:
                version = available.get(slug)
                if version is None:
                    raise ValueError("Skill 未发布、已归档或无读取权限")
                if selection != "latest":
                    version = selection
                destination = state.package_path(slug, version)
                if not state.owned(destination):
                    body = api.get("/skills/" + slug + "/package", version, archive=True)
                    state.install(slug, version, body)
                data["resolved"][selector(slug, selection)] = version
            except ApiError as error:
                if error.status == HTTPStatus.UNAUTHORIZED and error.code == "invalid_token":
                    raise
                if error.status == HTTPStatus.NOT_FOUND and error.code == "skill_unavailable":
                    clear_slug(data, slug)
                    available.pop(slug, None)
                if error.status == HTTPStatus.NOT_FOUND and error.code == "version_unavailable":
                    data["resolved"].pop(selector(slug, selection), None)
                problem(data, slug, selection, scopes, error)
            except (ValueError, OSError, HTTPException, BadZipFile) as error:
                problem(data, slug, selection, scopes, error)
        data["lastConnected"] = state.timestamp()
    except ApiError as error:
        if error.status == HTTPStatus.UNAUTHORIZED and error.code == "invalid_token":
            revoke_all(data)
        data["issues"].append(str(error))
    except KeyError:
        data["issues"].append("设备尚未绑定，或服务端返回的数据无法识别")
    except (URLError, ValueError, OSError, HTTPException) as error:
        data["issues"].append(str(error))

    state.save(data)
    cleanup(data)
    state.save(data)
    return not data["issues"]


def cleanup(data):
    """先持久化启用状态，再清理旧文件。目录占用时下次同步重试。"""
    active = {state.package_path(key.split("@", 1)[0], version) for key, version in data["resolved"].items()}
    for path in state.installed():
        if path not in active:
            try:
                state.retire(path)
            except OSError as error:
                data["issues"].append(f"无法移除已停用的目录 {path}：{error}")


def clear_slug(data, slug):
    for key in list(data["resolved"]):
        if key.startswith(slug + "@"):
            data["resolved"].pop(key)


def problem(data, slug, selection, scopes, error):
    data["issues"].append(f"{', '.join(sorted(scopes))} / {slug} ({selection})：{error}")
