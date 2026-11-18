# Skill Inventory

Skill Inventory 在 Windows 本机提供 Skill 编辑、发布、授权分发和 Codex 同步。管理员管理草稿、版本和角色，普通用户查看并下载获授权的版本，为自己的客户端创建可撤销的设备令牌。

## 便携演示

在 Windows x64 完整解压演示 ZIP，双击 `Start-Demo.cmd`。网页、API、后台同步和桌面客户端会一起启动，首次运行自动生成演示账号、发布数据和三个 Codex 项目。首次初始化后，可以双击同目录的 `Skill-Inventory-Client.exe` 重新打开桌面客户端。操作顺序和验收判据见 [演示验收](docs/demo-acceptance.md)。

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

安装后可运行 `skill-inventory-gui` 打开桌面客户端。窗口提供设备绑定、后台启停、立即同步、同步状态和项目规则。选中项目即可检查 Codex 实际启用的版本，或在该目录打开 Codex。关闭窗口后后台同步继续，使用「停止后台」可结束同步。便携包会自动打开客户端窗口。

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

## 构建便携演示包

开发机还需完整安装的 Windows x64 Python 3.14.7（含 Tcl/Tk 9）和 Codex 原生 Windows x64 CLI 0.169.1。从仓库构建时需要 Git，从便携包的 `source/` 重建时使用随包源码清单。准备下列文件到 `tmp/demo-inputs`。构建脚本会核对三个输入的 SHA-256。

- [Eclipse Temurin 21.0.13+9 Windows x64 JRE](https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jre_x64_windows_hotspot_21.0.13_9.zip)，保存为 `temurin.zip`
- [CPython 3.14.7 Windows amd64 embeddable](https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip)，保存为 `python.zip`
- [Codex 0.169.1 LICENSE](https://raw.githubusercontent.com/openai/codex/rust-v0.169.1/LICENSE)，保存为 `codex-license.txt`

从 Codex npm 平台包 `@openai/codex-win32-x64` 取出其 `vendor/x86_64-pc-windows-msvc` 整个目录。

```powershell
python demo/build.py --inputs tmp/demo-inputs --codex 'C:/path/to/x86_64-pc-windows-msvc' --output tmp/demo-release
```

输出包括可直接运行的展开目录、分发 ZIP 和 SHA-256。构建会运行 Java 测试、Vue 类型检查和构建以及 Python 客户端测试，还会用系统自带的 .NET Framework C# 编译器生成 `Skill-Inventory-Client.exe`。EXE 从包内加载 Python 和桌面客户端源码。从仓库构建时，ZIP 包含 Git 已跟踪文件和未忽略的新源码，构建前先检查工作树；从分发源码重建时，新增源码要加入 `SOURCE-FILES.txt`。

开发调试可复用演示数据。第一次运行展开目录的 `Start-Demo.cmd`，通过菜单 6 取得本轮目录，按 Q 关闭三端。在源码目录执行以下命令，使用同一份 SQLite 数据库和演示账号。

```powershell
$env:INVENTORY_DB = 'C:/path/to/Skill-Inventory-Demo/demo-data/run-xxxxxxxxxxxx/inventory.db'
pwsh -NoProfile -File ./start.ps1 -ApiPort 18747 -WebPort 15173
```

用浏览器打开 `http://127.0.0.1:15173` 验证前端热更新。若需同时调试客户端，退出开发服务后重新用便携菜单启动，或从菜单 7 打开的隔离命令窗口在开发 API 运行时执行 `inventory sync` 和 `inventory codex --list-skills`。开发服务和便携服务轮流使用同一端口及数据库。
