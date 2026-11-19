# Skill Inventory 便携演示与验收

## 1. 启动

1. 在 Windows x64 上完整解压 ZIP，双击 `Start-Demo.cmd`。包内含 Java、Python、桌面客户端和网页构建。
2. 等待控制台显示网页和 API 地址。首次优先使用端口 `18747`，端口占用时会自动选择可用端口。
3. 首次打开桌面客户端会显示登录弹窗，并填入下表的 `demo-dev` 账号和密码。点击「登录」进入主界面，项目列表为空，所有 Skill 默认未勾选。「记住账号和密码」默认未勾选。勾选并登录成功后，退出回到弹窗时会重新填充账密。窗口关闭后可按 `8` 或双击同目录下的 `Skill-Inventory-Client.exe` 重新打开。

| 账号 | 初始密码 | 权限 |
| --- | --- | --- |
| `admin` | `88888888` | 管理员 |
| `demo-dev` | `88888888` | Dev |
| `demo-qa` | `88888888` | QA |
| `demo-both` | `88888888` | Dev 和 QA |

这些公开账号仅用于新初始化的本机便携演示。沿用旧演示数据时，菜单 `5` 可查看该轮初始化账号。若验收时修改了密码，请使用修改后的密码，或用 `Start-Demo.cmd --fresh` 单独开启新一轮。

浏览器通过同一 API 管理和读取 SQLite 中的草稿、发布版本及角色。Windows 客户端默认每 5 秒检查更新，将勾选的版本写入所选目录。登录后可在主界面修改「同步间隔（秒）」并点击「保存」，后台无需重启。登录会话保存在当前 Windows 用户的凭据管理器，数据库、配置和日志保存在随包的 `demo-data/run-…`。文件选择器使用当前 Windows 用户的真实目录。

| 菜单 | 操作 |
| --- | --- |
| 1 / 2 / 3 | 查看已同步文件 / 查看后台状态 / 立即同步 |
| 4 / 5 / 6 | 暂停或恢复网页与 API / 查看账号 / 打开数据目录 |
| 7 / 8 / Q | 打开客户端命令窗口 / 打开桌面客户端 / 结束演示 |

## 2. 用户级与项目级同步

| 应用范围 | 如何操作 | 首次同步后应看到 |
| --- | --- | --- |
| 用户级 | 保持默认目录，在「启用」列勾选迭代简报 | `~/.skills-inv/skills/sprint-brief--2.0.0/SKILL.md` |
| 项目 A | 单击「选择项目目录」登记一个可写目录。切换到该项目，单独勾选迭代简报，再通过「查看可选版本」选择固定版本 `1.5.1`，点「保存规则」 | `<项目 A>/.agents/skills/sprint-brief--1.5.1/SKILL.md` |
| 项目 B | 再登记另一个可写目录，切换到该项目。先保留未勾选，检查文件后再勾选 | 未勾选时该项目没有迭代简报副本。勾选并同步后出现 `<项目 B>/.agents/skills/sprint-brief--2.0.0/SKILL.md` |

每次调整后可点「立即同步」，用控制台菜单 `1` 查看路径，或在资源管理器中打开对应 `SKILL.md`。正文标记分别为 `SPRINT-151` 和 `SPRINT-200`。各范围独立保存勾选状态。取消项目 B 的勾选并同步时，只有项目 B 的受管副本被移除。完成本步骤后，可重新勾选项目 B 以继续验证更新。

## 3. 发布、权限与恢复

| 账号 | 可见内容 |
| --- | --- |
| `admin` | 迭代简报、测试交接、发布检查清单，可编辑与授权 |
| `demo-dev` | 迭代简报，默认 `2.0.0` |
| `demo-qa` | 测试交接 `1.0.0` |
| `demo-both` | 迭代简报 `2.0.0` 与测试交接 `1.0.0` |

在同一浏览器窗口切换账号前，先用右上角「退出」。

| 场景 | 操作与通过判据 |
| --- | --- |
| 草稿与历史 | 管理员预览迭代简报草稿，看到 `SPRINT-210-DRAFT`。下载 `1.5.1` 和 `2.0.0`，核对正文标记和 `2.0.0` 的 `references/checklist.md`。重复发布 `2.0.0` 应报版本已存在 |
| 导入 | 在菜单 `6` 打开的数据目录中找到 `release-checklist.zip`。管理员将它导入发布检查清单并发布 `1.0.0`，Dev 与双角色账号可下载 |
| 更新 | 管理员将迭代简报发布为 `2.1.0`。等待两个同步周期或立即同步。用户级和项目 B 升级到 `2.1.0`，项目 A 保留 `1.5.1`。另外发布 `1.9.0` 时，最高版本仍为 `2.1.0` |
| 断线 | 菜单 `4` 暂停服务，菜单 `3` 立即同步，应报告连接失败。菜单 `2` 仍显示后台运行，原文件仍在。再次按 `4` 恢复并同步 |
| 撤权 | 管理员取消迭代简报的 Dev 授权并保存。立即同步后各范围的对应受管副本消失，Dev 和双角色账号无法取得该技能历史。恢复授权并同步后文件重新出现 |
| 重启 | 先按 `Q` 再双击同一个 `Start-Demo.cmd`。网页历史、项目列表、勾选状态和固定版本均保持，桌面端可继续同步 |
| 归档 | 管理员归档迭代简报并立即同步。管理员仍可查看历史，普通账号无法下载，桌面列表条目和各范围的受管副本消失 |
| 退出与失效 | 先勾选仍有权限的发布检查清单并同步。桌面端点击「退出登录」，受管副本消失。再次登录，核对文件恢复。管理员随后在账号页修改 demo-dev 密码或停用账号，立即同步后旧会话应失效，受管副本消失。重新启用账号后需使用当前密码登录 |

## 4. HTTP 与故障定位

把控制台显示的 API 地址（含 `/api/v1`）填入提示。以下 PowerShell 7 命令用平台账号登录并逐项验证授权。

~~~powershell
$base = Read-Host '粘贴演示控制台显示的 API 地址'
$headers = @{ 'X-Skill-Inventory' = '1' }
$login = @{ username = (Read-Host '账号'); password = (Read-Host '密码' -MaskInput) }
try {
    Invoke-RestMethod "$base/session" -Method Post -ContentType 'application/json' -Headers $headers `
        -Body ($login | ConvertTo-Json -Compress) -SessionVariable session
} finally {
    Remove-Variable login
}
try {
    foreach ($path in '/skills', '/skills/sprint-brief', '/skills/sprint-brief/versions',
                      '/skills/sprint-brief/content?version=1.5.1',
                      '/skills/sprint-brief/package?version=1.5.1') {
        try {
            if ($path -like '*/package?*') {
                Invoke-WebRequest "$base$path" -WebSession $session -OutFile sprint-brief-1.5.1.zip
                "$path -> ZIP 已保存"
            } else {
                Invoke-RestMethod "$base$path" -WebSession $session
            }
        } catch {
            if (!$_.Exception.Response) { throw }
            "$path -> HTTP $([int]$_.Exception.Response.StatusCode)"
        }
    }
} finally {
    Invoke-RestMethod "$base/session" -Method Delete -Headers $headers -WebSession $session
    Remove-Variable session
}
~~~

归档前 Dev 能读取对应正文和 ZIP，QA 的四条迭代简报请求应返回 404。退出会话后，再读取这些接口会返回 401。

- 执行 `Start-Demo.cmd --fresh --no-browser --verify` 可快速验收网页构建、API、后台启动及新实例的空勾选状态。
- 正常停机用菜单 `Q`。`--restart` 重启当前演示，`--fresh` 建立一轮新的演示配置并保留旧数据。若想清理旧一轮在真实目录中写入的副本，请先在旧一轮取消勾选并同步，再使用 `--fresh`。
- 菜单 `6` 可查看 `server.log`、`worker.log` 或 `desktop.log`，以及当前轮的临时账号文件。分享时使用原始 ZIP。
