[简体中文](README.md) | English

# HKSTP quickstart

Install official Codex with your own login, history and VPN egress, even when sharing a Linux account.

**1. On the cluster, create your own directory.** Replace `alice` with your name.
For user83, `~/alice` means `/home/dyvm6xra/dyvm6xrauser83/alice`.

```bash
mkdir -p ~/alice
cd ~/alice
```

**2. Clone and start setup.** Choose your Codex alias, such as `alice-codex`.

```bash
git clone --branch feat/hkstp-setup https://github.com/celia-hk-infra/webstudio-utils.git
cd webstudio-utils
./setup-hkstp.sh
```

When it asks for `connection.env`, leave setup open and do step 3.

**3. On your MacBook, connect your VPN and start the egress host.** Requires Homebrew and Python 3.

```bash
brew install gost
brew install --cask devtunnel
git clone --branch feat/hkstp-setup https://github.com/celia-hk-infra/webstudio-utils.git
cd webstudio-utils
bash scripts/start_egress_host.sh --language en
```

Keep the Mac awake, VPN connected and host running. Copy
`vendor/codex-local-egress/connection.env` to `~/alice/connection.env` on the cluster.
Enter its **absolute path** in the waiting setup. Use the same GitHub/Microsoft
account for Dev Tunnels on both machines, then complete Codex login.

**4. On the cluster, activate your alias and run Codex.** Use the alias you chose.

```bash
source ~/.bashrc
alice-codex
alice-codex --egress status   # Check connectivity; show tmux name and log path
alice-codex --egress logs     # Show recent logs
alice-codex --egress restart  # Restart only your connection
```

[HKSTP options and troubleshooting](docs/hkstp.en.md) · [WebStudio / ModelArts guide](docs/webstudio.en.md)
