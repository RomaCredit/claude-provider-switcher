# Claude Provider Switcher

`claude-provider-switcher`（命令简称 `ccs`）用于管理 Claude Code 的 provider
配置。它会切换 `ANTHROPIC_BASE_URL`、模型和认证方式，切换前自动备份用户级
settings，同时保留权限、hooks 等无关设置。

它**不是** Claude Desktop 对话迁移工具，也不会改动 Claude Code 的会话历史。
Claude Code 的最终配置还会受到环境变量、项目 settings、命令行参数和组织托管
策略影响，因此每次切换后都应执行 `ccs doctor`，并在 Claude Code 中查看
`/status`。

## 安装

要求 Python 3.10+。首版从 GitHub 分发，**尚未发布到 PyPI**。
已有 pipx 的环境可以直接安装：

```bash
pipx install git+https://github.com/RomaCredit/claude-provider-switcher.git
ccs --version
```

也可以克隆到本地后在虚拟环境安装：

```bash
git clone https://github.com/RomaCredit/claude-provider-switcher.git
cd claude-provider-switcher
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/ccs --version
```

Windows 对应路径为 `.venv\Scripts\python.exe` 和 `.venv\Scripts\ccs.exe`。
Ubuntu/Debian 提示 `externally-managed-environment` 时不要强行绕过系统保护，
可改用上面的虚拟环境、pipx，或独立安装脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/RomaCredit/claude-provider-switcher/v0.1.0/install.sh | sh
ccs --version
```

独立脚本要求 Python 3.10+，会同时安装 `ccs` 和
`claude-provider-switcher`，安装过程不会修改 Claude 配置。Windows：

```powershell
irm https://raw.githubusercontent.com/RomaCredit/claude-provider-switcher/v0.1.0/install.ps1 | iex
```

## 快速开始

```bash
ccs profile list
ccs profile add gateway --base-url https://gateway.example.com --model your-model --auth-kind auth_token
ccs use gateway
ccs status
ccs doctor
```

请把示例地址和模型替换为自己的网关配置。`profile add` 默认会隐藏输入密钥；
自动化场景可使用 `--key-stdin`。macOS
优先使用 Keychain，Windows 优先使用 Credential Manager，POSIX fallback 文件为
`credentials.json` 且权限为 `0600`。密钥不会写入 `profiles.json`、状态输出或 URL。

## Profile

默认配置：

```text
macOS/Linux: ~/.claude-provider-switcher/profiles.json
Windows:     %USERPROFILE%\.claude-provider-switcher\profiles.json
```

内置 `official` 订阅 profile 和 `anthropic` API profile。用户 profile 与内置
profile 使用同一套逻辑，可以编辑或删除。

API profile 的地址必须提供 Anthropic Messages API，即 Claude Code 使用的
`/v1/messages`。只有 OpenAI `/v1/chat/completions` 的端点不能直接使用，除非
网关负责协议转换。`api_key` 使用 `x-api-key`，`auth_token` 使用 Bearer token。

## 命令

```text
ccs use <name>                         备份并更新用户 settings
ccs run <name> [-- claude 参数]       以隔离配置启动一次 Claude
ccs status [--json]                    显示本地配置和凭据后端
ccs doctor [--json]                    检查 shell、项目和托管配置冲突
ccs profile list
ccs profile add <name> [选项]
ccs profile edit <name> [选项]
ccs profile key <name> [--key-stdin]
ccs profile test <name> [--inference]
ccs profile remove <name> --yes
ccs backup list
ccs backup restore <id> --yes
```

`profile test` 默认发起无请求体的 `/v1/models` 探测；一些 Anthropic 网关不提供
该接口，可以显式使用 `--inference` 发送一个 token 的 `/v1/messages` 请求，这
可能产生费用。探测成功不代表流式输出、工具调用或所有 Claude Code 功能都兼容。

`ccs use official` 只把用户 settings 切换到 Claude.ai 登录模式，不会自动登录、
注销、删除 OAuth 文件，也不会绕过组织策略。切换后重启 Claude Code 并查看
`/status`。

## 安全机制

每次 `use` 或恢复都会在 `~/.claude-provider-switcher/backups/` 生成带时间戳的备份；
写入使用原子替换和锁。工具拒绝替换 symlink settings、拒绝不安全的远程 HTTP
地址、拒绝 URL 内嵌凭据，并且不会在报错中输出密钥。

持久切换会把 `apiKeyHelper` 写入 settings，只含 Python 和 helper 的路径、数据
目录、profile 名称。Claude 运行 helper，通过 stdout 获取密钥；这是机器专用通道，
不是普通状态输出。Claude 会把 helper 的凭据同时放进 `x-api-key` 和 Bearer 两个
认证头；网关只接受其中一个头时，用 `ccs run`。更换安装位置后要重新 `ccs use`
以更新 helper 路径。

备份可能含原有 settings 中的明文密钥，因此同样限制文件权限。Windows 使用仅允许
当前用户访问的 ACL，POSIX 使用 `0600`。删除 profile 不会删除历史备份；请按敏感
文件管理备份。独立安装器保留旧版本目录，避免已有 helper 引用失效。

`ccs run` 清理继承到子进程的 provider 环境变量，并使用用户 settings 的去除 provider
字段后的副本，禁用项目和本地 settings 来源。它会保留 hooks 和权限等其他用户设置，
**不是沙箱**，也不会绕过组织策略。切换器不会为 run 持久写入 settings，但 Claude
自身仍可能正常保存会话。`ccs doctor` 不能检查 MDM、注册表、远程策略或交互式 CLI
参数，最终生效配置仍以 Claude `/status` 为准。

切换器不收集遥测，仅在用户主动执行 probe 时请求配置的 provider。安装器会下载
发布文件，`ccs run` 启动的 Claude Code 自身网络行为不受本项目的无遥测承诺覆盖。

## 开发与测试

```bash
python -m unittest discover -s tests -v
```

测试使用临时目录和假凭据，HTTP 探测仅指向 loopback。本机设置
`CCS_TEST_REAL_CLAUDE=1` 可额外验证真实 Claude Code 的 `auth status` 配置读取，
不会发起推理请求。POSIX 安装器在 Linux/macOS CI 运行。测试通过不代表已经验证所有
第三方网关的推理、流式输出或工具调用行为。

## 许可证

MIT
