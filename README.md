# Skill Inventory

Skill Inventory 在 Windows 本机提供 Skill 编辑、发布、授权分发和 Codex 同步。管理员管理草稿、版本和角色，普通用户查看并下载获授权的版本，为自己的客户端创建可撤销的设备令牌。

## 启动网页和 API

准备 PowerShell 7.4+、JDK 21+、Maven 3.9+、Node.js 22.12+ 和 npm。使用客户端还需 Python 3.12+ 和已装好的 Codex CLI。

从仓库根目录运行：

~~~powershell
pwsh -NoProfile -File ./start.ps1
~~~

首次启动时，为内置账号 **admin** 设置密码，至少 10 个字符且 UTF-8 编码最多 72 字节。网页地址为 **http://127.0.0.1:5173**，API 地址为 **http://127.0.0.1:8787/api/v1**。按 Ctrl+C 停止前后端。端口已被占用时可运行：

~~~powershell
pwsh -NoProfile -File ./start.ps1 -ApiPort 18747 -WebPort 15173
~~~

数据默认保存在 data/inventory.db，日志保存在 data/logs。重启保留 SQLite 中的账号、角色关系、设备令牌摘要、草稿和已发布版本。浏览器会话在进程重启后需重新登录。可通过 INVENTORY_DB 指定已有父目录下的其他数据库路径。

如果首次启动在写入管理员账号前中断，可使用 `./start.ps1 -InitializeAdmin` 重新输入初始密码。服务仅在缺少管理员时使用该密码。

## 发布和授权

1. 以 admin 登录，创建 Skill 草稿，填写唯一 slug、显示名称和描述。编写 SKILL.md 或在草稿中上传 ZIP，确认 Markdown 预览和文件清单。ZIP 根目录必须包含 UTF-8 的 SKILL.md，元数据包含 name 和 description。
2. 发布时填写版本号，例如 1.5.1。随后修改草稿，再发布 2.0.0。发布快照保持固定。默认读取按三段数字比较得到的最高版，历史版本可按完整版本号获取。
3. 在权限页创建两个普通账号和对应角色，在 Skill 详情中授权所需角色。普通用户重新登录或继续使用当前会话即可看到授权范围。账号拥有多个角色时获得这些角色授权的并集。
4. 用户在设备令牌页创建令牌，并将仅展示一次的令牌输入客户端。用户可在同页撤销设备令牌。归档停止分发全部版本，管理员仍能查看历史。

SQLite 将 Skill 草稿和发布快照分别存放于 skill 和 release。account 与 role 通过 account_role 关联，Skill 与角色通过 skill_role 关联。device_token 关联账号并保存令牌摘要。消费接口在每次请求时检查当前授权。

## 调用 HTTP API

先在网页签发设备令牌，再运行以下 PowerShell 7 示例。将示例 slug 和版本改成账号有权读取的已发布 Skill。

~~~powershell
$base = 'http://127.0.0.1:8787/api/v1'
$slug = 'my-skill'
$version = '1.5.1'
$token = Read-Host '设备令牌' -MaskInput
$headers = @{ Authorization = "Bearer $token" }
try {
    Invoke-RestMethod "$base/skills" -Headers $headers
    Invoke-RestMethod "$base/skills/$slug" -Headers $headers
    Invoke-RestMethod "$base/skills/$slug/versions" -Headers $headers
    Invoke-RestMethod "$base/skills/$slug/content?version=$version" -Headers $headers
    Invoke-WebRequest "$base/skills/$slug/package?version=$version" -Headers $headers -OutFile "$slug-$version.zip"
} finally {
    Remove-Variable token, headers
}
~~~

详情、正文和 ZIP 接口省略 version 时使用最高版本。设备令牌失效时返回 401，Skill 或版本在当前账号下不可获取时返回 404。

## 使用 Windows 客户端

从仓库根目录安装。以下命令均以当前 Windows 用户执行。

~~~powershell
python -m pip install ./client
python -m skill_inventory.cli configure http://127.0.0.1:8787 --interval 60
python -m skill_inventory.cli enable my-skill
python -m skill_inventory.cli enable my-skill --version 1.5.1 --project C:/projects/pinned
python -m skill_inventory.cli disable my-skill --project C:/projects/disabled
python -m skill_inventory.cli sync
python -m skill_inventory.cli start
python -m skill_inventory.cli status
~~~

将项目路径换成已存在的目录。其他项目继承用户级设置。使用 inherit my-skill --project 路径删除项目覆盖。使用 stop 停止后台同步。设备令牌保存在 Windows 凭据管理器，启用规则和最近同步结果保存在 %LOCALAPPDATA%\SkillInventory。

进入项目后，用以下入口启动 Codex。加 --list-skills 可从真实 Codex 检查受管技能和启用状态。

~~~powershell
python -m skill_inventory.cli codex
~~~

该入口应用项目选定的版本，并报告和避开启用中的手动同名 Skill。直接运行 codex 会走宿主默认发现流程，项目启用范围由专用入口保证。后台服务启动时同步，之后按间隔检查。断网保留最近成功安装。服务端明确撤权、归档或撤销设备令牌后，下次同步停用相应受管副本。已启动的 Codex 会话可在重新启动后按新规则加载。参见 [Codex 接入决策](docs/adr/0001-codex-skill-activation.md)。

## 开发验证

~~~powershell
mvn -B -f server/pom.xml test
npm --prefix web ci
npm --prefix web run build
python -m compileall -q client/src
python -m unittest discover -s client/tests
~~~

测试范围和交付验收见 [首版需求](docs/requirements.md)。
