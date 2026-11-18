"""通过真实 API 准备注入数据，并生成可手工上传的示例 ZIP。"""

import http.cookiejar
from io import BytesIO
import json
import urllib.request
import zipfile


class Session:
    def __init__(self, origin):
        self.origin = origin
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )

    def request(self, method, path, payload=None, content_type="application/json"):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.origin + "/api/v1" + path, data=payload, method=method,
            headers={"X-Skill-Inventory": "1", "Content-Type": content_type},
        )
        with self.opener.open(request, timeout=5) as response:
            if response.headers.get_content_type() == "application/json":
                return json.load(response)

    def login(self, username, password):
        self.request("POST", "/session", {"username": username, "password": password})

    def upload(self, slug, archive):
        import secrets

        boundary = secrets.token_hex(24)
        head = (f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="demo.zip"\r\n'
                "Content-Type: application/zip\r\n\r\n")
        payload = head.encode("ascii") + archive + f"\r\n--{boundary}--\r\n".encode("ascii")
        self.request("PUT", f"/admin/skills/{slug}/package", payload,
                     f"multipart/form-data; boundary={boundary}")


def markdown(slug, description, body):
    return f"---\nname: {slug}\ndescription: {description}\n---\n\n# {description}\n\n{body}\n"


def scenario_zip(source, reference):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", source)
        archive.writestr("references/checklist.md", reference)
    return buffer.getvalue()


def seed(origin, passwords, root):
    admin = Session(origin)
    admin.login("admin", passwords["admin"])
    for role in ("Dev", "QA"):
        admin.request("POST", "/admin/roles", {"name": role})
    roles = {row["name"]: row["id"] for row in admin.request("GET", "/admin/roles")}
    memberships = {"demo-dev": ["Dev"], "demo-qa": ["QA"], "demo-both": ["Dev", "QA"]}
    for username in memberships:
        admin.request("POST", "/admin/accounts", {"username": username, "password": passwords[username]})
    accounts = {row["username"]: row["id"] for row in admin.request("GET", "/admin/accounts")}
    for username, assigned in memberships.items():
        admin.request("PUT", f"/admin/accounts/{accounts[username]}/roles",
                      {"ids": [roles[name] for name in assigned]})

    def draft(slug, title, role, body):
        skill = {"slug": slug, "name": title, "description": f"{role} 角色演示技能",
                 "source": markdown(slug, title, body)}
        admin.request("POST", "/admin/skills", skill)
        admin.request("PUT", f"/admin/skills/{slug}/roles", {"ids": [roles[role]]})
        return skill

    def publish(slug, version):
        admin.request("POST", f"/admin/skills/{slug}/releases", {"version": version})

    sprint = draft("sprint-brief", "迭代简报", "Dev", "SPRINT-151：按进度、阻塞两栏整理。")
    publish("sprint-brief", "1.5.1")
    source = markdown("sprint-brief", "迭代简报", "SPRINT-200：按进度、风险、下一步三栏整理。")
    admin.upload("sprint-brief", scenario_zip(source, "# 2.0.0 检查清单\n确认风险和负责人。\n"))
    publish("sprint-brief", "2.0.0")
    sprint["source"] = markdown("sprint-brief", "迭代简报",
                                 "SPRINT-210-DRAFT：保留风险栏，补充风险负责人和截止日期。")
    admin.request("PUT", "/admin/skills/sprint-brief", sprint)

    draft("qa-handbook", "测试交接", "QA", "QA-100：列出回归范围及待复测项。")
    publish("qa-handbook", "1.0.0")
    draft("release-checklist", "发布检查清单", "Dev", "待上传 ZIP，当前只有草稿。")
    sample = markdown("release-checklist", "发布检查清单", "RELEASE-100：确认回滚版本与审批记录。")
    (root / "release-checklist.zip").write_bytes(
        scenario_zip(sample, "# 发布清单\n1. 核对版本。\n2. 核对回滚操作。\n"))


def issue_device(origin, password):
    session = Session(origin)
    session.login("demo-dev", password)
    return session.request("POST", "/device-tokens", {"name": "Portable demo"})["token"]
