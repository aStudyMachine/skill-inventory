# Skill Inventory

Skill Inventory 在 Windows 本机提供 Skill 编辑、发布、授权分发和目录同步。管理员管理草稿、版本和角色，普通用户查看并下载获授权的版本，并使用同一账号登录桌面客户端。

## 便携演示

在 Windows x64 完整解压演示 ZIP，双击 `Start-Demo.cmd`。网页、API、后台同步和桌面客户端会一起启动。首次运行会初始化演示账号和发布数据。未登录时，桌面客户端先显示登录弹窗。使用 [演示验收](docs/demo-acceptance.md) 所列的 `demo-dev` 账号登录，启用项与项目列表默认为空。首次初始化后，可以双击同目录的 `Skill-Inventory-Client.exe` 重新打开客户端。

## 启动网页和 API

准备 PowerShell 7.4+、JDK 21+、Maven 3.9+、Node.js 22.12+ 和 npm。使用客户端还需 Python 3.12+。

从仓库根目录运行：

~~~powershell
pwsh -NoProfile -File ./start.ps1
~~~

首次启动时，为内置账号 **admin** 设置密码，至少 10 个字符且 UTF-8 编码最多 72 字节。网页地址为 **http://127.0.0.1:5173**，API 地址为 **http://127.0.0.1:8787/api/v1**。按 Ctrl+C 停止前后端。端口已被占用时可运行：

~~~powershell
pwsh -NoProfile -File ./start.ps1 -ApiPort 18747 -WebPort 15173
~~~

数据默认保存在 data/inventory.db，日志保存在 data/logs。重启保留 SQLite 中的账号、角色关系、客户端登录会话、草稿和已发布版本。浏览器会话在进程重启后需重新登录。可通过 INVENTORY_DB 指定已有父目录下的其他数据库路径。

如果首次启动在写入管理员账号前中断，可使用 `./start.ps1 -InitializeAdmin` 重新输入初始密码。服务仅在缺少管理员时使用该密码。

## 发布和授权

1. 以 admin 登录，创建 Skill 草稿，在 SKILL.md 顶部的 YAML frontmatter 填写 name 和 description。name 只能使用小写字母、数字和单个连字符分隔，最多 64 字符，并在整个库中唯一。首次发布前可改名，发布后名称固定，归档继续保留该名称。ZIP 导入也以根目录 UTF-8 SKILL.md 的元数据为准。
2. 发布时填写版本号，例如 1.5.1。随后修改草稿，再发布 2.0.0。发布快照保持固定。默认读取按三段数字比较得到的最高版，历史版本可按完整版本号获取。
3. 在权限页创建两个普通账号和对应角色，在 Skill 详情中授权所需角色。普通用户重新登录或继续使用当前会话即可看到授权范围。账号拥有多个角色时获得这些角色授权的并集。
4. 用户以现有账号和密码登录客户端。管理员可通过修改密码或停用账号使既有登录失效。归档停止分发全部版本，管理员仍能查看历史。

SQLite 将 Skill 草稿和发布快照分别存放于 skill 和 release。account 与 role 通过 account_role 关联，Skill 与角色通过 skill_role 关联。client_session 关联账号并保存客户端会话摘要。消费接口在每次请求时检查当前授权。

升级旧数据库前先停服务并备份 SQLite 数据库。启动时会以各草稿和发布包的 SKILL.md 元数据迁移旧记录，保留授权、发布版本与原始 ZIP。重复名称、无效元数据或同一个 Skill 的草稿与历史名称不一致会中止迁移，启动日志会指出有问题的记录。升级后请重新登录客户端。若旧标识与新名称不同，请在本机重新勾选正式名称，移除旧规则。

## 调用 HTTP API

以下 PowerShell 7 示例先使用平台账号登录，再通过会话读取发布内容。将名称和版本改成账号有权读取的已发布 Skill。

~~~powershell
$base = 'http://127.0.0.1:8787/api/v1'
$name = 'my-skill'
$version = '1.5.1'
$headers = @{ 'X-Skill-Inventory' = '1' }
$login = @{ username = (Read-Host '账号'); password = (Read-Host '密码' -MaskInput) }
try {
    Invoke-RestMethod "$base/session" -Method Post -ContentType 'application/json' -Headers $headers `
        -Body ($login | ConvertTo-Json -Compress) -SessionVariable session
} finally {
    Remove-Variable login
}
try {
    Invoke-RestMethod "$base/skills" -WebSession $session
    Invoke-RestMethod "$base/skills/$name" -WebSession $session
    Invoke-RestMethod "$base/skills/$name/versions" -WebSession $session
    Invoke-RestMethod "$base/skills/$name/content?version=$version" -WebSession $session
    Invoke-WebRequest "$base/skills/$name/package?version=$version" -WebSession $session -OutFile "$name-$version.zip"
} finally {
    Invoke-RestMethod "$base/session" -Method Delete -Headers $headers -WebSession $session
    Remove-Variable session
}
~~~

详情、正文和 ZIP 接口省略 version 时使用最高版本。登录失效时返回 401，Skill 或版本在当前账号下不可获取时返回 404。

## 使用 Windows 客户端

从仓库根目录安装。以下命令均以当前 Windows 用户执行。

安装后可运行 `skill-inventory-gui` 打开桌面客户端。首次输入服务端地址、账号和密码，点击「登录」。需要定时同步时点击「启动后台」，便携包会自动启动该进程。用「用户级目录」指定用户级根目录，用「选择项目目录」登记项目根目录。选择的是根目录，客户端会补上 `.agents/skills/`，窗口会显示完整同步位置。目录和规则保存后，点击「立即同步」，或等待后台同步。关闭窗口后后台同步继续，使用「停止后台」可结束同步。便携包会自动打开客户端窗口。

~~~powershell
python -m pip install ./client
python -m skill_inventory.cli login http://127.0.0.1:8787 my-account --interval 60
python -m skill_inventory.cli enable my-skill
python -m skill_inventory.cli add-project C:/projects/another-project
python -m skill_inventory.cli enable my-skill --version 1.5.1 --project C:/projects/pinned
python -m skill_inventory.cli disable my-skill --project C:/projects/disabled
python -m skill_inventory.cli sync
python -m skill_inventory.cli start
python -m skill_inventory.cli status
~~~

用户级根目录默认是 `~/.skills-inv`。在「应用范围」选择用户级或一个已登记的项目，在每个 Skill 的「启用」列独立勾选。勾选默认跟随最新版，也可在下方保存固定版本。同步后在该范围的 `.agents/skills/<名称>--<版本>/SKILL.md` 验收。取消勾选或移除项目后，下次同步会清理对应的受管副本，手动文件会保留。

客户端会话保存在 Windows 凭据管理器，关闭客户端或重启服务后仍可使用。桌面端登录时可勾选「记住账号和密码」，成功后将账密单独保存到 Windows 凭据管理器，仅为同一服务端填充。退出只撤销会话，再次登录时取消勾选可清除已记住的账密。启用规则和最近同步结果保存在 `%LOCALAPPDATA%\SkillInventory`。

进入项目后，用以下入口启动 Codex。加 --list-skills 可从真实 Codex 检查受管技能和启用状态。

~~~powershell
python -m skill_inventory.cli codex
~~~

此可选入口使用设备上安装的 Codex，宿主仍按自己的搜索路径发现 Skill。便携演示以文件落盘验收。后台服务启动时同步，之后按间隔检查。断网保留最近成功安装。服务端明确撤权、归档、停用账号或修改密码后，下次同步停用相应受管副本。客户端退出登录会撤销当前会话并清理受管副本。参见 [Codex 接入决策](docs/adr/0001-codex-skill-activation.md)。

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

开发机还需完整安装的 Windows x64 Python 3.14.7（含 Tcl/Tk 9）。从仓库构建时需要 Git，从便携包的 `source/` 重建时使用随包源码清单。准备下列文件到 `artifacts/demo-inputs`。构建脚本会核对两个输入的 SHA-256。

- [Eclipse Temurin 21.0.13+9 Windows x64 JRE](https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jre_x64_windows_hotspot_21.0.13_9.zip)，保存为 `temurin.zip`
- [CPython 3.14.7 Windows amd64 embeddable](https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip)，保存为 `python.zip`

```powershell
python demo/build.py --inputs artifacts/demo-inputs --output artifacts/demo-release
```

每次构建为解压目录、ZIP 和校验文件追加本机时间戳。同一 `--output` 目录内，新包完整生成后会清理历史 ZIP、校验文件和未产生运行数据的旧解压目录。含 `demo-data` 的旧目录会保留。

输出包括可直接运行的展开目录、分发 ZIP 和 SHA-256。构建会运行 Java 测试、Vue 类型检查和构建以及 Python 客户端测试，还会用系统自带的 .NET Framework C# 编译器生成 `Skill-Inventory-Client.exe`。EXE 从包内加载 Python 和桌面客户端源码。从仓库构建时，ZIP 包含 Git 已跟踪文件和未忽略的新源码，构建前先检查工作树；从分发源码重建时，新增源码要加入 `SOURCE-FILES.txt`。

开发调试可复用演示数据。第一次运行展开目录的 `Start-Demo.cmd`，通过菜单 6 取得本轮目录，按 Q 关闭三端。在源码目录执行以下命令，使用同一份 SQLite 数据库和演示账号。

```powershell
$env:INVENTORY_DB = 'C:/path/to/Skill-Inventory-Demo/demo-data/run-xxxxxxxxxxxx/inventory.db'
pwsh -NoProfile -File ./start.ps1 -ApiPort 18747 -WebPort 15173
```

用浏览器打开 `http://127.0.0.1:15173` 验证前端热更新。若需同时调试客户端，退出开发服务后重新用便携菜单启动，或从菜单 7 打开的命令窗口在开发 API 运行时执行 `inventory sync`，然后核对同步目录。开发服务和便携服务轮流使用同一端口及数据库。
