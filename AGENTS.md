# Repository Guidelines

如果 Agent 未自动加载用户级指令，开始工作前先读取 `~/.agents/AGENTS.md`。

## 项目结构

- `server/` 包含 Spring Boot API 和 SQLite 数据库结构。Java 源码和 HTTP 集成测试分别位于 `server/src/main/java/` 和 `server/src/test/java/`。
- `web/src/` 包含基于 Vue 3 和 TypeScript 的管理界面、共用 API 调用和样式。Vite 入口为 `web/index.html`。
- `client/src/skill_inventory/` 包含 Python 命令行、Tk 桌面界面和后台同步逻辑。客户端测试位于 `client/tests/`，Windows 启动器、演示数据和打包脚本位于 `demo/`。

## 构建、测试与运行

在 Windows 的仓库根目录运行以下命令。

- `pwsh -NoProfile -File ./start.ps1` 启动 API 和管理网页，首次运行时提示初始化管理员账号。
- `mvn -B -f server/pom.xml test` 运行服务端 JUnit 集成测试。
- `npm --prefix web ci` 按锁定版本安装前端依赖。`npm --prefix web run build` 运行 `vue-tsc` 类型检查并用 Vite 构建前端。
- `python -m pip install -e ./client` 以可编辑模式安装客户端。`python -m unittest discover -s client/tests` 运行客户端回归测试。
- 构建便携包前，按 [README](README.md) 准备运行时文件，并按 [演示验收指南](docs/demo-acceptance.md) 在 Windows 上验证。

## 编码与测试约定

- Java 和 Python 使用四个空格缩进，Vue 和 TypeScript 使用两个空格。文件命名沿用 `InventoryApi.java`、`SkillsView.vue` 和 `test_sync.py` 等现有模式。注释、文档字符串和命令行帮助使用中文。
- 为行为变更添加针对性的回归测试。Java 测试文件使用 `*Test.java`，Python 测试文件使用 `test_*.py`。修改相关逻辑时，验证无权限时拒绝访问、同步中断后的处理，以及手动安装的 Skill 是否保留。
- 修改业务行为前查阅 [需求文档](docs/requirements.md)。涉及 Codex 的 Skill 发现机制或安装位置时查阅 [Codex 接入决策](docs/adr/0001-codex-skill-activation.md)。本机凭据、SQLite 数据和生成的便携包不入库。

## 本地产物与临时文件

- 可复用的构建输入放在 `artifacts/demo-inputs/`，待交付的便携包和校验文件放在 `artifacts/demo-release/`。构建方式见 [README](README.md)。
- `tmp/` 只存当次任务的临时脚本、日志和解压验收文件。每项任务使用独立子目录，验收结束后清理本次生成的内容。发现历史目录中仍有演示数据库或用户文件时，先确认保留范围。

## 提交与拉取请求

提交信息注明改动范围并使用简短的中文摘要，例如 `feat(client): 交付 Windows 桌面客户端和便携 EXE`。拉取请求中说明行为变更和验证结果，有相关议题时附链接，涉及界面变更时附截图。
