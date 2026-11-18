---
status: accepted
---

# 按项目控制 Codex 中的 Skill 生效

Codex 可以同时发现用户级和项目级的同名 Skill。为了让同一 Windows 用户的不同项目分别继承、固定版本或禁用同一个 Skill，客户端根据本机用户级和项目级配置确定该项目的生效结果，并以 Codex 实际发现的可用 Skill 验收。平台账号的角色授权控制服务端分发，按项目生效的规则由设备上的客户端管理。 [Codex 技能加载位置](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)

优先保留可信 Git 项目中直接执行 `codex` 的启动方式。先实测可信项目配置能否按路径停用用户级安装，且保留用户原有的技能配置。若该方案无法通过验收，使用专用入口应用项目配置后启动 Codex。 [Codex 技能禁用规则](https://learn.chatgpt.com/docs/build-skills#enable-or-disable-local-codex-skills) · [Codex 项目配置](https://learn.chatgpt.com/docs/config-file/config-advanced#project-config-files-codexconfigtoml)

在 Windows 使用 Codex CLI 0.169.1 和三个隔离的可信 Git 项目测试时，`config/read` 显示项目配置已进入有效配置，但 `skills/list` 在固定版项目仍启用了用户级版本，在禁用项目也继续启用它。首版因此采用 `skill-inventory codex` 专用入口。入口保留宿主已有规则，并为受管 Skill 路径追加当前项目所需的禁用规则。

用同一版本的真实 Codex app-server 验收专用入口时，继承项目启用 2.0.0，固定项目仅启用 1.5.1，禁用项目没有启用该 Skill。手动安装的独立 Skill 保持原有禁用状态，启用中的手动同名 Skill 保留原文件，受管副本停用并报告冲突。后续评估原生接入时，以 `skills/list` 的实际启用结果为准，同时检查已有手动 Skill 及其配置。
