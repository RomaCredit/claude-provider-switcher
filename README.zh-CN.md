# Claude Provider Switcher

`claude-provider-switcher`（命令简称 `ccs`）用于管理 Claude Code 的 provider
配置。它会切换 `ANTHROPIC_BASE_URL`、模型和认证方式，切换前自动备份用户级
settings，同时保留权限、hooks 等无关设置。

它**不是** Claude Desktop 对话迁移工具，也不会改动 Claude Code 的会话转录文件；
切换 provider 不会隐藏任何会话，详见[会话历史](#会话历史)。
Claude Code 的最终配置还会受到环境变量、项目 settings、命令行参数和组织托管
策略影响，因此每次切换后都应执行 `ccs doctor`，并在 Claude Code 中查看
`/status`。

## 安装

要求 Python 3.10+。首版从 GitHub 分发，**尚未发布到 PyPI**。
已有 pipx 的环境可以直接安装：

```bash
pipx install https://github.com/RomaCredit/claude-provider-switcher/archive/refs/tags/v0.1.3.zip
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
curl -fsSL https://raw.githubusercontent.com/RomaCredit/claude-provider-switcher/v0.1.3/install.sh | sh
ccs --version
```

独立脚本要求 Python 3.10+，会同时安装 `ccs` 和
`claude-provider-switcher`，安装过程不会修改 Claude 配置。Windows：

```powershell
irm https://raw.githubusercontent.com/RomaCredit/claude-provider-switcher/v0.1.3/install.ps1 | iex
```

## 快速开始

使用 APIMaster 时，地址、模型、认证方式和兼容选项已经按其
[Claude Code 文档](https://apimaster.ai/docs/en/cli/claude-code) 预填：

```bash
ccs use apimaster
```

第一次只需隐藏输入自己的 API key，以后切换会复用已保存的密钥。
直接运行 `ccs`，在 **Switch provider** 中选择 `apimaster` 也是同样的流程。
“预配置”不包含共享 API key，也不会从 Codex 配置中擅自复制凭据。

其他 Anthropic 兼容服务可以自行添加：

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

内置 `official` 订阅、`anthropic` 官方 API 和 `apimaster` 三个 profile。
APIMaster 预设内容：

```json
{
  "type": "api",
  "base_url": "https://apimaster.ai",
  "model": "claude-sonnet-4-6",
  "auth_kind": "auth_token",
  "env": {
    "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"
  }
}
```

Claude Code 使用的是根地址，**不能照搬 Codex 预设的 `/v1` 后缀**。
用户 profile 与内置 profile 使用同一套逻辑，均可编辑或删除。
可选 `env` 只允许上述两个兼容选项，值必须为字符串 `"0"` 或 `"1"`，
不允许存储密钥或任意环境变量；切换到其他 profile 后会清理这些兼容选项。

### 从旧版升级

使用安装脚本的用户重新运行上方 `v0.1.3` 安装命令即可。
通过 pipx 安装的用户执行：

```bash
pipx install --force https://github.com/RomaCredit/claude-provider-switcher/archive/refs/tags/v0.1.3.zip
ccs --version
ccs profile list
```

旧版运行过的机器也会出现 APIMaster：新版首次加载时，把 `profiles.json`
从格式版本 1 升级为 2，只补入缺少的新预设。原文件先备份到同目录下的
`profiles-v1-<id>.backup.json`，已有同名自定义配置、其他 profile 和密钥均保留，
不会自动切换 Claude 的当前设置。升级后主动删除的预设不会再次自动出现。
**不要删除原配置文件来升级。** 若要降级到 0.1.1 或更早版本，先恢复版本 1 的备份。
非交互环境先用 `ccs profile key apimaster --key-stdin` 从安全输入流保存密钥，
再执行切换。

API profile 的地址必须提供 Anthropic Messages API，即 Claude Code 使用的
`/v1/messages`。只有 OpenAI `/v1/chat/completions` 的端点不能直接使用，除非
网关负责协议转换。`api_key` 使用 `x-api-key`，`auth_token` 使用 Bearer token。

## 命令

```text
ccs use <name>                         备份并更新用户 settings，随后校正历史记录
ccs run <name> [-- claude 参数]       以隔离配置启动一次 Claude
ccs repair-history [--check] [--json]  只校正项目记录，不切换 profile
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

## 会话历史

切换 provider 不会隐藏任何会话。Claude Code 不在会话上记录 provider，因此没有
任何按 provider 过滤历史的机制，而本工具只改写 `settings.json`。转录文件始终位于
`<claude-home>/projects/<编码后的工作目录>/<session>.jsonl`；`ccs run` 会把
`CLAUDE_CONFIG_DIR` 指向同一目录，所以 `ccs run <name> -- --resume` 可以继续在
任何其他 profile 下开始的会话。

真正会分裂的是按原始工作目录字符串索引的项目记录。Windows 上 CLI 写入
`D:/WorkSpace/app`，桌面端写入 `D:\WorkSpace\app`，同一个目录留下两条记录，
导致信任状态、已授权工具、MCP 配置和历史提示补全被拆开。`ccs use` 在切换后会
自动校正这些记录，`ccs repair-history` 也可以单独执行：

```text
ccs repair-history --check          只报告重复项，不写入；发现问题返回 1
ccs repair-history                  备份两个文件后合并
ccs use <name> --no-repair-history  只切换，不校正
```

合并采用镜像而非收敛：同一目录的每种路径写法都会写入合并后的内容，冲突时以
字段更完整的那条为准，这样桌面端刚创建的空壳记录不会把信任状态重置掉。写入前
`.claude.json` 和 `history.jsonl` 都会复制到 `backups/history-<id>/`。历史提示
只会改成 Claude Code 自己用过的写法，转录文件永远不被改写或删除。

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
Windows 测试会用临时凭据验证 Credential Manager；macOS CI 设置
`CCS_TEST_NATIVE_KEYCHAIN=1` 验证 Keychain。发布标签还会触发三个平台的在线安装测试。

## 许可证

MIT
