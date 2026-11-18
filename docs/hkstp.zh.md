# HKSTP 共享账号安装

每个人使用独立目录。例如 Bob 将仓库放在 `~/demo-user/webstudio-utils`，
Alice 放在 `~/demo-user2/webstudio-utils`。分别在各自的仓库中运行：

```bash
./setup-hkstp.sh --name bob-codex  # Alice 使用 alice-codex
```

默认将仓库父目录作为个人目录，也可用 `--root /absolute/person-dir` 指定。
脚本安装官方 `@openai/codex`（默认 `0.166.0`），配置个人出口连接，并提供
Codex 设备码登录。脚本仅向共享的 `~/.bashrc` 添加指定名称的别名，保留其他
人的别名，并检查 `~/.bashrc`、`~/.bash_aliases` 和 PATH 中可执行命令的重名。
无法检测仅在当前 Shell 或其他加载文件中定义的别名。
将安装结束时打印的 alias 命令粘贴到当前终端即可使用；
新的交互式 Bash 终端会自动加载。之后可在任何项目目录运行：

```bash
bob-codex
bob-codex resume
bob-codex login --device-auth  # 安装时跳过登录的情况
bob-codex --egress status
bob-codex --egress logs
bob-codex --egress stop
bob-codex --egress start
bob-codex --egress restart
bob-codex --egress login github  # 或 microsoft，用于更新 Dev Tunnels 登录
```

非交互脚本应直接使用 `~/demo-user/bin/codex`。启动器固定选择该个人目录的
Codex 数据和出口配置，清除继承的 Codex/OpenAI 路由环境变量，必要时启动
个人出口，并在健康检查通过后运行 Codex（`--help` 和 `--version` 除外）。
出口不可用时会报错，不会切换到其他服务商。下一次调用 Codex 会重新启动
已停止的个人出口；此安装不创建开机服务。
启动器传入 `--no-daemon`，使交互会话使用当前出口环境，避免后台 Codex 服务
保留修改前的代理配置。

工具安装在个人目录的 `tools/`，Codex 配置、文件凭据和历史记录放在
`.hkstp/codex/`，出口配置、Dev Tunnels 凭据和日志放在 `.hkstp/egress/`。
每个人使用独立的 tmux 服务和会话。`--egress status` 检查代理连通性，并显示
tmux 服务名称和日志路径。重复安装保留已有登录、历史和 Codex 偏好。
脚本不加载 `shell/init.sh`、不链接 `~/.codex`、不复制共享凭据，也不安装
VS Code 或修改共享的默认 `codex`。启动器记录绝对路径，安装后请保留仓库及
个人目录的位置。目录隔离可以防止误用账号，但无法隔离拥有相同 Linux UID
的用户之间的文件访问权限。

先在个人电脑/Mac/VPS 上运行 `bash scripts/start_egress_host.sh`（依赖安装
见 [WebStudio 指南](webstudio.zh.md) 末尾的出口主机说明），保持其运行，将生成的 `connection.env` 复制到
集群。每个人自己的隧道两端须使用相同的 Dev Tunnels 账号。安装时会询问文件
路径和登录方式，也可显式指定：

```bash
./setup-hkstp.sh --name bob-codex --connection /path/to/connection.env --provider github
./setup-hkstp.sh --name bob-codex --defer-egress  # 先安装，之后再连接
./setup-hkstp.sh --help
```

`--skip-login` 只跳过 Codex 登录；出口仍需要有效的 Dev Tunnels 登录。
`--codex-version X.Y.Z` 可选择其他官方 npm 版本。安装要求 Linux、Python 3.8+、
Bash、Git 和 curl。优先使用已有的 Node/npm、tmux 和 Dev Tunnels。
缺少 Node/npm 时下载并校验 Node 22 LTS 压缩包（需要 tar/xz）；缺少 tmux 时
通过 Conda 安装（支持 `CONDA_EXE`），两者都没有时须先安装 tmux。
缺少 Dev Tunnels 时从微软下载到个人工具目录。Dev Tunnels 需要兼容的 ICU；
版本检查失败时，请安装 ICU 或将可运行的 `devtunnel` 加入 PATH 后重试。
GOST 只需要安装在个人电脑/VPS 出口主机上。

当前出口客户端会将主机选择的端口映射到集群的同一端口。脚本检查端口冲突，
不会停止其他人的隧道。发生冲突时，停止自己的电脑/VPS 主机进程，移走主机的
`connection.env` 并重新启动主机，以生成新的隧道和端口。将新文件复制到集群，
使用 `--connection` 重新运行安装。替换已有配置前先运行
`bob-codex --egress stop`。不要只修改一端的端口，两端配置必须一致。
进程被强制终止后可能残留 `.hkstp/egress/.connect.lock`；查看日志并确认自己的
客户端与监督进程已停止后，才可删除该锁目录。正常停止会自动清理。
