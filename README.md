简体中文 | [English](README.en.md)

# HKSTP 快速开始

安装官方 Codex，通过自己的 VPN 出口连接；即使共用 Linux 账号，每个人也有独立的登录、历史记录和出口配置。

**1. 在集群上创建个人目录。** 将 `alice` 换成自己的名字。
对于 user83，`~/alice` 的完整路径是 `/home/dyvm6xra/dyvm6xrauser83/alice`。

```bash
mkdir -p ~/alice
cd ~/alice
```

**2. 克隆仓库并开始安装。** 按提示选择个人 Codex 别名，例如 `alice-codex`。

```bash
git clone --branch feat/hkstp-setup https://github.com/celia-hk-infra/webstudio-utils.git
cd webstudio-utils
./setup-hkstp.sh
```

询问 `connection.env` 路径时，保留安装终端，先完成第 3 步。

**3. 在自己的 MacBook 上连接 VPN，启动出口主机。** 需要 Homebrew 和 Python 3。

```bash
brew install gost
brew install --cask devtunnel
git clone --branch feat/hkstp-setup https://github.com/celia-hk-infra/webstudio-utils.git
cd webstudio-utils
bash scripts/start_egress_host.sh --language zh
```

保持 Mac 唤醒、VPN 连接和主机脚本运行。将生成的
`vendor/codex-local-egress/connection.env` 复制到集群的 `~/alice/connection.env`，
在等待的安装提示中输入该文件的**绝对路径**。两台机器的 Dev Tunnels 使用同一个
GitHub/Microsoft 账号登录，然后完成 Codex 登录。

**4. 回到集群，加载别名并运行 Codex。** 使用安装时选择的别名。

```bash
source ~/.bashrc
alice-codex
alice-codex --egress status   # 检查连接，显示 tmux 名称和日志路径
alice-codex --egress logs     # 查看最近日志
alice-codex --egress restart  # 仅重启自己的连接
```

[HKSTP 选项与故障排查](docs/hkstp.zh.md) · [WebStudio / ModelArts 指南](docs/webstudio.zh.md)
