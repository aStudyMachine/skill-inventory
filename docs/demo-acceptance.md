# Skill Inventory 便携演示与验收

目标是在另一台 Windows x64 设备上，从解压后的目录启动网页、API 和后台客户端，并通过随包 Codex 验证实际 Skill 启用状态。建议预留 20–30 分钟。验收顺序先验证基线，再发布新版本，最后验证撤权、归档和令牌撤销。

## 1. 运行环境与入口

1. 将 `Skill-Inventory-Demo-Windows-x64.zip` 和同名 `.sha256` 复制到目标设备。可在系统自带 PowerShell 执行 `Get-FileHash .\Skill-Inventory-Demo-Windows-x64.zip`，与 `.sha256` 里的值比对。
2. 用资源管理器完整解压到用户可写的本地目录，进入 `Skill-Inventory-Demo`。双击 **Start-Demo.cmd**。直接从 ZIP 预览窗口运行会缺少相邻文件。
3. 等待控制台显示网页地址、API 地址和数据目录。默认浏览器会打开 **http://127.0.0.1:18747**，桌面客户端会同时打开。首次启动会建库、生成密码、通过 API 注入演示数据、绑定并启动客户端。控制台按 `5` 查看演示网页账号和密码。
4. 双击默认续用上轮数据。要恢复初始场景，在解压目录打开命令提示符执行 `Start-Demo.cmd --fresh`。旧数据继续保留。退出使用菜单 `Q`。若换端口，可执行 `Start-Demo.cmd --fresh --port 18748`，续用此轮时继续指定 `--port 18748`。

首次启动完成后，桌面窗口如果已关闭，可以双击解压目录里的 **Skill-Inventory-Client.exe**，也可以在演示控制台按 `8`。EXE 会打开当前演示的客户端和三个项目，复用已有设备绑定。EXE 依赖同目录的 `runtime/` 和 `source/`，移动时请保留整个解压目录。仅启动 EXE 时，网页和 API 由原有演示进程提供。

目标机使用 Windows x64、有默认浏览器并允许当前用户使用 Windows 凭据管理器。随包提供 Java、Python、Codex 原生 CLI、Vue 静态构建和 Python 依赖。以普通 Windows 用户运行即可。本流程里的 Codex 实测使用宿主的 Skill 发现接口，可离线执行。菜单 7 可进一步打开正式 Codex 对话入口，该环节需要在该演示环境中另行登录并联网。

### 三端和数据流

```text
浏览器 / Vue 管理与消费网页
             │ 同源 HTTP /api/v1
             ▼
Spring Boot API ────────────────► SQLite
             ▲                   草稿 / 发布快照 / 角色 / 令牌摘要
             │ 设备令牌 + 每次请求判权
             │
Windows 后台客户端 ──────────────► 隔离的受管 Skill 文件
             │                         │
             │ 每 5 秒检查              ▼
             └──────────────► Codex 专用入口按项目启用
                                   ├─ inherit    最新版
                                   ├─ pinned     1.5.1
                                   └─ disabled   未启用
```

浏览器用会话 Cookie 登录。客户端用 Windows 凭据管理器中的设备令牌请求同一 API。网页与 API 由一个 Java 进程在同一端口提供，菜单 4 暂停它们时客户端继续运行。

## 2. 初始数据与菜单

| 账号 | 角色 | 首次打开 Skill 库应看到 |
| --- | --- | --- |
| `admin` | 内置管理员 | 迭代简报、测试交接、发布检查清单，可编辑和授权 |
| `demo-dev` | Dev | 迭代简报，默认 `2.0.0` |
| `demo-qa` | QA | 测试交接 `1.0.0` |
| `demo-both` | Dev、QA | 迭代简报 `2.0.0` 与测试交接 `1.0.0` |

`sprint-brief` 是迭代简报。其 `1.5.1` 正文含 `SPRINT-151`，`2.0.0` 正文含 `SPRINT-200` 且 ZIP 附有 `references/checklist.md`。管理员草稿含 `SPRINT-210-DRAFT`，后面将发布为 `2.1.0`。`release-checklist` 是 Dev 有权查看的技能，初始只有草稿。`qa-handbook` 独立授给 QA。设备令牌 **Portable demo** 属于 `demo-dev`，已自动绑定客户端。

| 菜单 | 操作 |
| --- | --- |
| 1 | 用随包的真实 Codex 检查三个项目，只显示实际启用的 `sprint-brief` 版本 |
| 2 | 显示客户端的 `running`、`resolved`、`issues` 与同步记录 |
| 3 | 立即同步，当场看到连接或权限变化的结果 |
| 4 | 暂停或恢复网页与 API，供离线验证 |
| 5 | 显示本轮临时账号密码 |
| 6 | 打开当前数据目录，查看样例 ZIP、数据库、项目和日志 |
| 7 | 打开隔离的命令提示符，内含 `inventory` 命令和项目目录 |
| 8 | 重新打开已关闭的桌面客户端窗口 |
| Q | 结束网页、API 和后台同步。菜单 7 另外打开的命令窗口可用 `exit` 关闭 |

## 3. 完整验收流程

客户端常用操作可以从桌面窗口完成。表格中的菜单操作也可用于核对同一结果。

| 客户端操作 | 窗口操作与通过判据 |
| --- | --- |
| 查看后台状态 | 顶部显示已绑定账号 `demo-dev`、后台运行状态、最近检查与连通时间 |
| 重新绑定设备 | 在网页用获授权账号签发设备令牌。桌面窗口填写演示地址、设备令牌和同步间隔，点「绑定设备」。通过时显示对应账号，令牌输入框清空 |
| 检查三个项目 | 在「应用范围」下拉框选 `inherit`、`pinned`、`disabled`，逐个点「检查 Codex 启用」。首次分别显示 `2.0.0`、`1.5.1` 和没有启用的受管 Skill |
| 修改项目规则 | 选择项目和对应 Skill，选择继承、跟随最新版、固定版本或停用。固定版本可点「查看可选版本」后在版本框选择。点「保存规则」，再点「立即同步」和「检查 Codex 启用」核对 |
| 验证后台独立 | 关闭窗口，控制台菜单 2 应仍显示 `running: true`。菜单 8 重新打开窗口，用「停止后台」和「启动后台」分别验证状态；整场演示用 Q 退出 |
| 打开 Codex | 在窗口选择项目后点「启动 Codex」。该按钮会在对应项目目录打开独立 Codex 控制台，离线验收可只用「检查 Codex 启用」 |

同一浏览器窗口中的角色通过页面右上角「退出」后重新登录切换。并排观察时用不同浏览器配置文件。发布、归档、撤权等写操作会推进本轮状态，重跑整场请用 `--fresh`。

```text
管理员草稿 ──发布 2.1.0──► 新的不可变快照
                               │ 设备轮询
                ┌──────────────┼───────────────┐
                ▼              ▼               ▼
           inherit 升级   pinned 保留旧版   disabled 继续停用
                │              │
                ├── API 不可达 ─┤ 保留各自版本
                └── 撤权或归档 ─┘ 两个项目均停用
```

| 顺序 | 操作 | 通过判据 |
| --- | --- | --- |
| A. 开机 | 完整解压并双击；菜单 2、1 | 网页进入登录页。客户端 `running: true`。真实 Codex 返回 `inherit 2.0.0`、`pinned 1.5.1`、`disabled 未启用` |
| B. 草稿与快照 | 管理员打开迭代简报，点「Markdown 预览」并依次打开历史 `1.5.1` 和 `2.0.0`；尝试再次发布 `2.0.0` | 草稿含 `SPRINT-210-DRAFT`，两个历史快照分别含 `SPRINT-151`、`SPRINT-200`。重复发布显示该版本已发布 |
| C. 角色并集与下载 | 依次用三个普通用户登录核对上表；用 Dev 查看迭代简报，切换 `1.5.1` 并下载，再切回 `2.0.0` 下载 | 普通用户仅看到授权发布项。两版正文与对应 ZIP 一致；`2.0.0` 有附带文件 |
| D. ZIP 导入 | 管理员打开发布检查清单，在「导入或替换 ZIP」选择菜单 6 数据目录下的 `release-checklist.zip`；检查根 `SKILL.md`、附带清单和 `RELEASE-100` 后发布 `1.0.0` | Dev 和双角色账号刷新后能看到并下载；QA 刷新后依旧只有测试交接 |
| E. 后台更新 | 管理员为迭代简报发布草稿为 `2.1.0`。等待两个同步周期（约 10 秒），执行菜单 1 | `inherit 2.1.0`、`pinned 1.5.1`、`disabled 未启用`；Dev 网页默认打开 `2.1.0`，旧历史仍可下载 |
| F. 断线和恢复 | 菜单 4 暂停服务，菜单 3 同步，再用 2、1 检查；菜单 4 恢复并用菜单 3 同步 | 停机时报告连接失败，后台仍运行，已安装启用状态同 E。恢复后同步成功，浏览器重新登录可见 `2.1.0` |
| G. 当前授权 | 管理员进入迭代简报取消 Dev 角色勾选并保存；菜单 3、1。再授回 Dev，菜单 3、1 | 撤权后各项目都未启用该 Skill，Dev 和双角色账号均无法读取该 Skill 的任何历史版本。恢复后重现 E |
| H. 重启持久化 | 菜单 Q 退出，重新双击同一目录下的 Start-Demo.cmd。重新登录并用菜单 1 检查 | 网页仍可读取 `2.1.0` 和发布检查清单，项目启用与固定版本仍同 E，后台进程重新运行 |
| I. 归档 | 管理员归档迭代简报，菜单 3、1。分别观察管理员历史与 Dev 消费视图 | 管理员仍能查看历史；Dev 消费端列表移除该 Skill，最高版和历史版 URL 均不能下载，所有演示项目均未启用 |
| J. 令牌撤销 | Dev 登录「设备令牌」，撤销 **Portable demo**，点菜单 3 后用菜单 2 检查；完成后按 Q | 明确报告令牌无效或已撤销，`resolved` 为空。浏览器 Dev 会话仍可查看发布检查清单。后台和 Java 在菜单退出后停止 |

要把归档与令牌撤销对本地技能的影响分别展示得更明显，可在 I 后启用另一项仍有权限的 Skill，再执行 J。在菜单 7 的命令窗口运行 `inventory enable release-checklist`、`inventory sync`，进入 `projects\inherit` 后用 `inventory codex --list-skills` 查看。撤销后重新执行同一条列表命令，两个技能均无启用项。

### 补充验收

- 在步骤 C 后发布低于当前最高版的 `1.9.0`，Dev 的默认版本仍为 `2.0.0`，历史版本可以选到 `1.9.0`。
- 在步骤 A 后使用菜单 7 执行 `inventory enable sprint-brief --version 9.9.9 --project projects\pinned` 和 `inventory sync`。同步报告精确版本不存在，固定项目不会改为最新版。将上述命令中的 `9.9.9` 改回 `1.5.1` 并重新同步，恢复表中状态。
- 在步骤 A 后使用菜单 6，复制 `codex/skills/skill-inventory-managed/sprint-brief--2.0.0/SKILL.md` 到该数据目录下自建的 `codex/skills/manual-demo/SKILL.md`。菜单 1 报告同名冲突，受管副本停用，手工文件仍可打开。移除刚才复制的手工文件后，菜单 1 恢复原状态。

### 用 HTTP 直接核对权限与历史

在网页用待测账号签发一个额外的临时令牌。在系统 PowerShell 执行下列命令，端口改为演示窗口显示的值。令牌输入由提示隐藏。

```powershell
$base = 'http://127.0.0.1:18747/api/v1'
$secret = Read-Host '输入设备令牌' -AsSecureString
$token = [System.Net.NetworkCredential]::new('', $secret).Password
$headers = @{Authorization = "Bearer $token"}
try {
    foreach ($path in '/skills', '/skills/sprint-brief', '/skills/sprint-brief/versions',
                      '/skills/sprint-brief/content?version=1.5.1',
                      '/skills/sprint-brief/package?version=1.5.1') {
        try {
            if ($path -like '*/package?*') {
                Invoke-WebRequest "$base$path" -UseBasicParsing -Headers $headers -OutFile sprint-brief-1.5.1.zip
                "$path -> ZIP 已保存"
            } else {
                Invoke-RestMethod "$base$path" -Headers $headers
            }
        } catch {
            if (!$_.Exception.Response) { throw }
            "$path -> HTTP $([int]$_.Exception.Response.StatusCode)"
        }
    }
} finally {
    Remove-Variable secret, token, headers
}
```

Dev 在授权且未归档时返回列表、详情、版本记录、`SPRINT-151` 和 ZIP。QA 可获取自己的授权列表，调用同一 Skill 的详情、版本、正文和 ZIP 应得 HTTP 404。撤销用于此测试的临时令牌后，API 返回 HTTP 401。

## 4. 快速验收、续用和故障定位

- 目标机可执行 `Start-Demo.cmd --fresh --no-browser --verify`。它会建库、启动三端、调用真实 Codex 检查三个项目并退出，适合核对传输和初次启动；完整业务验收仍按 A–J 操作。
- 按菜单 6 查看当前目录。后端日志在 `server.log`，同步日志在 `worker.log` 或 `local/SkillInventory/worker.log`，桌面日志在 `desktop.log`。`accounts.json` 仅保存本轮网页账号密码。截图和对外分享时隐藏密码和令牌。
- 重建包时，如果导入 `_tkinter` 报 DLL 加载失败，检查随包 Python 目录中的 Tcl/Tk DLL 和 `zlib1.dll`。可以用随包的 `python.exe -m tkinter` 检查能否独立打开窗口。
- 端口被占用时启动会报错。优先回到原演示窗口按 Q 释放端口。演示期间用 Q 结束，直接关闭控制台或强制结束窗口可能留下后台进程。若暂时无法关闭旧会话，用新端口开启一轮。
- 每轮的 SQLite、客户端状态、Codex 配置和项目目录都在 `demo-data/run-…`。同步凭据由当前 Windows 用户的凭据管理器保存。复制成果时传原始 ZIP；接收方首次启动会生成自己的账号密码和设备凭据。
- 单独打开 Codex 的命令示例。在菜单 7 输入 `cd projects\inherit`，再输入 `inventory codex`。检查实际发现用 `inventory codex --list-skills`。直接执行 `codex` 会使用宿主自己的默认行为。
- 验收记录建议保存设备系统与架构、ZIP SHA-256、A–J 各步骤的实际结果和异常截图。压缩包中的 `source/` 含三端源码、依赖清单和测试。需要在开发机重建时，见其中 README 的「构建便携演示包」。
