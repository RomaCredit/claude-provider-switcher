# Claude Provider Switcher

`claude-provider-switcher`（命令简称 `ccs`）用于管理 Claude Code 的 provider
配置。它会切换 `ANTHROPIC_BASE_URL`、模型和认证方式，切换前自动备份用户级
settings，同时保留权限、hooks 等无关设置。

它**不是** Claude Desktop 对话迁移工具，也不会改动 Claude Code 的会话转录文件；
历史检查与校正的具体范围见[会话历史](#会话历史)，不保证所有客户端的历史显示行为。
Claude Code 的最终配置还会受到环境变量、项目 settings、命令行参数和组织托管
策略影响，因此每次切换后都应执行 `ccs doctor`，并在 Claude Code 中查看
`/status`。

## 安装

要求 Python 3.10+。首版从 GitHub 分发，**尚未发布到 PyPI**。
已有 pipx 的环境可以直接安装：

```bash
pipx install https://github.com/RomaCredit/claude-provider-switcher/archive/refs/tags/v0.1.4.zip
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
curl -fsSL https://raw.githubusercontent.com/RomaCredit/claude-provider-switcher/v0.1.4/install.sh | sh
ccs --version
```

独立脚本要求 Python 3.10+，会同时安装 `ccs` 和
`claude-provider-switcher`，安装过程不会修改 Claude 配置。Windows：

```powershell
irm https://raw.githubusercontent.com/RomaCredit/claude-provider-switcher/v0.1.4/install.ps1 | iex
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

使用安装脚本的用户重新运行上方 `v0.1.4` 安装命令即可。
通过 pipx 安装的用户执行：

```bash
pipx install --force https://github.com/RomaCredit/claude-provider-switcher/archive/refs/tags/v0.1.4.zip
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
ccs use <name>                         备份并切换 settings，随后只读检查历史
ccs run <name> [-- claude 参数]       以隔离配置启动一次 Claude
ccs repair-history [--check | --yes] [--json]
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

本工具不迁移、不读取或重写 `<claude-home>/projects/` 下的会话转录。
`ccs run` 保持相同的 `CLAUDE_CONFIG_DIR`，并允许传入 `--resume`、`--continue`；
实际能否恢复会话仍由 Claude Code 决定。这不是 Codex 的 `model_provider` 同步机制。

Windows 的项目记录可能同时使用 `D:/WorkSpace/app` 和 `D:\WorkSpace\app`，
导致同一目录的会话元数据、信任状态、工具或 MCP 配置不一致。**从 0.1.4 起，
普通 `ccs use` 和菜单切换只检查这些记录，不自动写入历史文件。**

```text
ccs repair-history --check --json   只读检查，不创建目录、文件或锁
ccs repair-history                  确认退出 Claude 后修复
ccs repair-history --yes            已退出 Claude 时供非交互脚本使用
ccs use <name> --no-repair-history  只切换，跳过历史检查
```

执行实际修复前，必须关闭所有 Claude Code 和相关桌面会话。只有已知且无冲突的会话
元数据（如 `lastSessionId`）可以补齐。若字段值不一致，或一方缺少信任、工具、
MCP、未知配置字段，该目录的全部项目记录和历史提示路径均原样保留，报告冲突数量。
不会按“字段多的一方”覆盖，不会自动合并授权范围。冲突需要在关闭 Claude 后人工处理，
报告不显示配置值和密钥。

无冲突目录保留各路径别名；`history.jsonl` 只采用已出现过的路径写法。
损坏行、BOM、CRLF/LF 和末尾缺少换行均保留，不删除提示或会话。
转录目录清单仅采用一种旧版编码规则作辅助报告，未匹配不代表目录失效或历史丢失。

`--check` 在有待修复项或未解决冲突时返回 1，两者都没有时返回 0。
两条路径记录已经一致，即使别名还在也返回 0；只有提示路径待修复时不会漏报。
实际修复完成但仍有冲突也返回 1。JSON 中 `pending_changes` 描述本次分析的输入，
`applied` 表示是否写入；完成后再次 `--check` 检查当前结果。

写入前把两个已存在的源文件逐字节备份到
`~/.claude-provider-switcher/backups/history-<id>/`，并限制访问权限。
每次暂存完成、替换前都检查两个源文件的内容与文件身份，检测到并发修改、删除、替换
或链接文件就停止。若只写入了第一份文件，错误会说明已完成的部分和备份位置，不自动
回滚覆盖其他进程的新数据。

**这不是 Claude 也会遵守的锁，也不是跨文件事务。** 最后一次检查后仍存在竞争窗口，
所以必须先退出 Claude；`--yes` 是退出确认，不是强制覆盖开关。
`history-*` 备份暂不支持 `ccs backup restore`：需要手工恢复时，先退出 Claude，
另存当前文件，对照报告中的源路径比较备份内的 `claude.json`、`history.jsonl`，
仅恢复确实需要的文件。备份可能含密钥，不能贴到公开 issue。
切换后的只读检查若失败会给出警告，但不会误报 provider 切换失败。

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
