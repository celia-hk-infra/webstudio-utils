简体中文 | [English](README.en.md)

# webstudio-utils

通过任意文件系统上的仓库副本，快速初始化新的 WebStudio 容器。安装脚本默认将仓库的父目录用于持久化数据；可通过 `WEBSTUDIO_PERSIST_ROOT` 指定其他位置。

- [初始化新容器](#初始化新容器)
- [目录与文件存放位置](#目录与文件存放位置)
- [选择智能体](#选择智能体)
- [凭据与网关配置](#凭据与网关配置)
- [容器重启后](#容器重启后)
- [迁移已有的 Codex 历史记录](#迁移已有的-codex-历史记录)
- [故障排查](#故障排查)
- [可用选项](#可用选项)

## 初始化新容器

请将仓库放在支持保留 Unix 权限的持久化挂载目录中，例如 `/home/user/work/dataset/user-sfs/webstudio-utils`：

```bash
cd /home/user/work/dataset/user-sfs/webstudio-utils
./setup_container.sh --tunnel-name my-jupyter  # 首次运行时指定隧道名称
source shell/init.sh                           # 为当前终端加载环境
codex resume                                   # 也可直接运行 codex
```

安装脚本还会通过 Conda 将 tmux 及其依赖安装到持久化存储的 `tools/tmux` 中，并使其在新终端中可用。首次安装需要 Conda，即使使用了 `--skip-vscode` 也一样。后续安装会复用该目录中的 tmux。容器更换后，正在运行的 tmux 会话会结束。

交互式安装会提示输入隧道名称（直接回车保留已保存或默认的名称），然后询问启动方式：后台运行（默认）、在当前终端运行，或暂不启动。后台选项会在名为 `vscode-tunnel` 的 tmux 会话中运行隧道，终端关闭后仍保持运行。使用 `--start-tunnel`（后台）或 `--start-tunnel=foreground` 可跳过询问直接选择，`--no-start-tunnel` 可跳过启动。无人值守运行默认不启动隧道，除非显式指定。`--skip-vscode` 会跳过隧道安装及启动询问，不能与 `--start-tunnel` 同时使用。

安装脚本会保存隧道名称，后续容器直接运行 `./setup_container.sh` 即可，无需再传入 `--tunnel-name`。脚本可以安全地重复运行。

安装后可直接管理隧道：

```bash
./scripts/start_vscode_tunnel.sh --background   # 后台启动
./scripts/start_vscode_tunnel.sh --status       # 查看是否已连接
./scripts/start_vscode_tunnel.sh --stop         # 停止后台会话
./scripts/start_vscode_tunnel.sh                # 在当前终端运行（Ctrl+C 停止）
```

隧道启动脚本也会加载 `shell/init.sh`，将智能体环境传递给 VS Code 终端。它会在持久化存储中保留隧道的 CLI 身份与登录数据，并复用已保存的名称。服务端安装在本地 `/tmp` 存储中，容器更换后会重新构建。如果保存的凭据过期或被撤销，仍可能需要重新登录。请勿在两个容器中同时使用同一隧道身份。

隧道名称最多为 20 个字符，只能包含字母、数字或连字符。可运行 `./setup_container.sh --tunnel-name SHORT-NAME` 修改已保存的名称。

## 目录与文件存放位置

| 位置 | 内容 |
| --- | --- |
| `user-sfs/.webstudio-agent-home` | Codex 会话、历史记录、配置及其他智能体状态 |
| `user-sfs/.webstudio-agent-home/gh` | GitHub CLI 登录数据 |
| `user-sfs/.webstudio-tunnel` | 隧道名称及 VS Code CLI 身份与登录数据 |
| `user-sfs/tools` 和 `cache` | 固定版本的 CLI 软件包、VS Code 运行环境及下载缓存 |
| `user-sfs/tools/gh` | 供新终端和新容器共用的 GitHub CLI 可执行文件 |
| `user-sfs/tools/tmux` | tmux 及其 Conda 依赖 |
| `/tmp/webstudio-$UID` | 本地 CLI 副本、VS Code CLI 及 VS Code 服务端 |

固定版本在 `setup_container.sh` 中定义：

| 工具 | 版本 | 覆盖变量 |
| --- | --- | --- |
| Codex CLI | `0.166.0` | `WEBSTUDIO_CODEX_VERSION` |
| Claude Code | `2.1.322` | `WEBSTUDIO_CLAUDE_VERSION` |
| GitHub CLI | `2.103.3` | `WEBSTUDIO_GH_VERSION` |

首次安装会将各软件包下载到持久化存储；每个新容器再将其复制到本地磁盘。VS Code CLI 的下载文件也会缓存在持久化存储中，然后在本地解压。VS Code 服务端使用的 Conda 运行环境保留在持久化存储中。容器内需要有 `node`、`npm`、`conda`、`curl` 和 `tar`；隧道启动脚本会检查平台要求。

## 选择智能体

在终端中运行安装脚本时，会显示选择菜单：使用上下方向键移动，空格键选中或取消选中，回车键继续。默认选中两个智能体；按 `q` 取消。随后，在隐藏输入的提示中输入 OpenLux API 密钥。安装脚本会为所有选中的智能体保存密钥，无需分别登录。再次运行时，如果所有选中的智能体都已有密钥，直接按回车即可保留现有凭据。

在脚本中运行（不显示选择菜单）时，请使用：

```bash
./setup_container.sh --agents both --skip-vscode
# 其他选项：--agents codex、--agents claude、--agents none
source shell/init.sh
```

没有终端时，默认安装两个智能体。除非所有选中的智能体都已有保存的密钥，否则需要通过环境变量或密钥管理器提供 `OPENLUX_API_KEY`。如果缺少凭据，安装会在下载前停止。选择 `--agents none` 会跳过密钥提示。`--skip-codex` 和 `--skip-claude` 会排除对应智能体，并且不显示选择菜单。跳过某个智能体不会卸载它。

两个 CLI 都缓存在 `tools/<agent>/<version>` 中，并复制到本地 `/tmp/webstudio-$UID` 下供运行使用。默认通过 `https://registry.npmmirror.com` 下载；设置 `WEBSTUDIO_NPM_REGISTRY=https://registry.npmjs.org` 可改用官方源。这不会修改全局 npm 设置。

## 凭据与网关配置

两个智能体均配置为使用 OpenLux。

**Codex。** 安装脚本会将 `$CODEX_HOME/config.toml` 中的顶层 `openai_base_url` 设为 `"https://api.openlux.ai/v1"`，保留其他设置，并设置 `cli_auth_credentials_store = "file"`，使认证信息持久化保存在 `$CODEX_HOME/auth.json` 中。密钥通过标准输入传给 `codex login --with-api-key`。重复运行安装脚本会重新应用该 URL；使用 `--skip-codex` 可跳过此步骤。

**Claude Code。** 安装脚本会在持久化的 `$CLAUDE_CONFIG_DIR/settings.json` 和 shell 环境中，将 `ANTHROPIC_BASE_URL` 设为 `https://api.openlux.ai`。Claude 会自行追加 `/v1/messages`。`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` 会通过 OpenLux 需要认证的 `/v1/models` 接口，将可用的 Claude 模型加载到 `/model` 中，包括接口新公布的版本。安装脚本会移除旧的 `CLAUDE_CODE_USE_GATEWAY` 设置，因为在此 CLI 版本中，该设置会禁用模型发现功能。

需要了解的细节：

- 模型发现需要 `ANTHROPIC_AUTH_TOKEN` 中包含 OpenLux 密钥。安装脚本会将输入的密钥保存为 `env.ANTHROPIC_AUTH_TOKEN`。
- 模型发现会更新模型选择列表，但不会自动切换当前选中的模型。安装脚本不会固定模型 ID，并会保留现有模型偏好。如果不想继续使用旧的默认模型，请自行移除固定到 4.x 版本的设置。
- 安装脚本会在持久化的 `$CLAUDE_CONFIG_DIR/.claude.json` 中将首次使用引导标记为已完成。否则，即使配置了 OpenLux API URL，引导流程仍会检查 Anthropic 的 OAuth 接口。

凭据以 `600` 权限保存在 Git 仓库之外的私有持久化智能体目录中。输入新密钥会替换所选智能体的 API 凭据，其他偏好设置保持不变。安装脚本不会打印密钥，也不会将其作为命令行参数传递。可用模型取决于你的 OpenLux 账户。

GitHub CLI 在验证官方发布文件的校验和后，会安装到 `tools/gh` 下。`shell/init.sh` 会将其加入 `PATH`，并将 `GH_CONFIG_DIR` 指向私有持久化存储。如果没有有效的登录状态，安装脚本会启动 GitHub 浏览器登录，将令牌以 `600` 权限保存为该私有目录中的文件，并配置 Git 使用 `gh` 进行 HTTPS 认证。后续安装会复用已保存的登录状态，并在容器更换后恢复 Git 凭据助手。令牌过期或被撤销后需要重新登录。

无人值守安装需要已有的登录状态、`GH_TOKEN` 或 `GITHUB_TOKEN`。通过环境变量提供的令牌需要在新容器中重新设置。使用 `--skip-gh-auth` 可仅安装 CLI，跳过 GitHub 认证配置。

## 容器重启后

在尚未完成安装时加载 `shell/init.sh`，脚本会检查 `WEBSTUDIO_LOCAL_DIR` 中的完成标记，并询问是否运行安装脚本。选择否后，终端仍可使用，同时会显示供之后运行的命令。没有终端时，脚本会显示命令并返回非零状态，不会等待输入。完成标记仅在安装成功后写入；请将 `WEBSTUDIO_LOCAL_DIR` 保持在容器本地的临时存储上，以便检测容器更换。

更换容器会清除主目录中的链接和本地可执行文件副本。重新运行安装脚本即可从持久化挂载目录恢复这些内容。仅保存在已清空的主目录中的状态无法恢复。

`shell/init.sh` 会将持久化智能体目录链接到 `$HOME`，并在 `.bashrc` 和当前使用的 Bash 登录配置文件中添加可重复执行而不产生重复内容的启动钩子，同时保留现有配置。登录终端和普通交互式终端均受支持，包括以 root 用户运行的容器。它会设置 `CODEX_HOME`、`CLAUDE_CONFIG_DIR` 和 `GH_CONFIG_DIR`，清除 Bash 的 `TMOUT`，并将本地 CLI 加入 `PATH`。安装脚本还会检查 Codex 守护进程控制目录是否为私有目录，并修复迁移后仍指向旧挂载位置的守护进程软件包链接。

安装完成后，在当前终端中加载 `shell/init.sh`；之后新开的 Bash 终端会自动加载。使用 `--norc` 启动的终端需要手动加载。新 Bash 终端会自动加载此环境，保存的凭据也会在容器重启后保留，因此无需再次导出密钥或单独登录：

```bash
source shell/init.sh
codex  # 或运行 claude
```

请使用实际运行智能体的用户执行安装。每个用户都需要独立安装，并使用自己的私有本地运行目录（默认为 `/tmp/webstudio-$UID`）。安装脚本不会修改其他用户的主目录，也不会在用户之间共享私有智能体状态。如果在同一挂载目录上切换用户，请将 `WEBSTUDIO_AGENT_STATE_DIR` 设置为该用户拥有的独立目录。

## 迁移已有的 Codex 历史记录

容器可能曾同时使用 `$HOME/.codex` 和旧初始化脚本的 `user/.webstudio-agent-home/.codex`。新安装脚本不会自动合并这些正在使用的目录。先确认哪个目录包含需要保留的会话，停止所有使用该目录的 Codex 进程，运行一次新安装脚本，再将该目录的内容复制到新挂载位置：

```bash
cp -a /home/user/work/dataset/user/.webstudio-agent-home/.codex/. \
  /home/user/work/dataset/user-sfs/.webstudio-agent-home/.codex/
```

如果要迁移 `$HOME/.codex`，请将源路径替换为 `$HOME/.codex/.`。在决定如何处理重复的数据库和会话文件之前，不要将一个来源直接覆盖到另一个来源上。复制时应停止 Codex，以保证 SQLite 数据库与会话文件的一致性。可以通过 `codex resume` 重新打开保存的对话，但容器终止时，正在执行的命令也会结束。

## 故障排查

### 安装脚本提示需要 700 权限

旧挂载目录可能始终将智能体主目录的权限显示为 `777`，即使执行 `chmod` 也不改变。反复修改权限无法修复不保留权限的挂载目录，也不应将凭据保存在该位置。请使用支持私有目录权限的挂载目录，例如 `user-sfs`。如果 shell 中仍保留旧仓库设置的覆盖变量，请先清除：

```bash
unset WEBSTUDIO_PERSIST_ROOT WEBSTUDIO_AGENT_STATE_DIR WEBSTUDIO_LOCAL_DIR
cd /home/user/work/dataset/user-sfs/webstudio-utils
./setup_container.sh
source shell/init.sh
```

### 其他问题

不完整的安装不会被复用。如果安装脚本提示 `tools/<agent>` 缓存或本地运行副本不完整，请将对应目录移到其他位置后重新运行。安装脚本以原子方式替换文件，因此执行中断不会留下只写入了一部分的配置文件。

## 可用选项

```bash
./setup_container.sh --help
./scripts/start_vscode_tunnel.sh --help
```

如需快速安装智能体而跳过 VS Code，请使用 `--skip-vscode`；如只需隧道，请使用 `--agents none`。在加载 `shell/init.sh` 前设置 `WEBSTUDIO_PERSIST_ROOT`、`WEBSTUDIO_AGENT_STATE_DIR` 或 `WEBSTUDIO_LOCAL_DIR`，可覆盖默认路径。隧道启动脚本支持 `CONDA_EXE`、`VSCODE_INSTALL_DIR`、`VSCODE_LOCAL_DIR`、`VSCODE_GLIBC_LINKER` 和 `VSCODE_CONDA_SOLVER`。
