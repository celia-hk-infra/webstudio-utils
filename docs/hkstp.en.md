# HKSTP shared-login setup

Use one directory per person, even when everyone logs in as the same Linux user.
For example, clone this repository into `~/demo-user/webstudio-utils` for Bob
and `~/demo-user2/webstudio-utils` for Alice. In each checkout, run:

```bash
./setup-hkstp.sh --name bob-codex  # Alice chooses alice-codex
```

Setup defaults to the checkout's parent directory; `--root /absolute/person-dir`
overrides it. It installs the official `@openai/codex` CLI (default `0.166.0`),
creates a personal launcher, configures personal egress, and offers Codex device
login. It appends a named alias to the shared `~/.bashrc`, preserving other aliases
and checking for conflicting names in `~/.bashrc`, `~/.bash_aliases`, and executables
on PATH. Aliases defined only in a running shell or other sourced files are not
detected. Run the alias line printed by setup in your current
terminal; future interactive Bash terminals load it automatically. Then use:

```bash
bob-codex
bob-codex resume
bob-codex login --device-auth  # if login was deferred
bob-codex --egress status
bob-codex --egress logs
bob-codex --egress stop
bob-codex --egress start
bob-codex --egress restart
bob-codex --egress login github  # or microsoft, if Dev Tunnels login expires
```

The shortcut works from any project directory. Scripts can invoke
`~/demo-user/bin/codex` directly; Bash aliases are intended for interactive shells.
The launcher always selects that person's Codex home and egress, clears inherited
Codex/OpenAI routing variables, and starts their connection if needed. Egress must
pass its health check before Codex runs, except for `--help` and `--version`.
There is no provider fallback. A stopped connection starts again on the next
Codex invocation; setup does not install a boot service.
The launcher passes `--no-daemon` so interactive sessions use the current egress
environment instead of retaining a previous proxy in a background Codex server.

Tools live in `tools/` under the person directory. Codex configuration, file-based
credentials and history live in `.hkstp/codex/`. Egress connection settings,
Dev Tunnels credentials and logs live in `.hkstp/egress/`. Each person has a
dedicated tmux server and session; starting or stopping one does not operate on
another person's session. `--egress status` checks the proxy and prints the tmux
server name and log path. Setup does not source `shell/init.sh`, link `~/.codex`,
copy shared credentials, install VS Code, or change the shared default `codex`.
Reruns preserve existing authentication, history and Codex preferences.
Keep the person directory and repository at their installed paths: launchers
record absolute paths. Separate directories avoid accidental account mixing;
they do not provide security isolation between people sharing the same Linux UID.

Before configuring egress, start the personal host on your laptop/Mac/VPS with
`bash scripts/start_egress_host.sh` (see the host instructions at the end of the
[WebStudio guide](webstudio.en.md)). Keep it running, and copy its `connection.env` to the cluster. Both ends
of each person's tunnel must sign in to the same Dev Tunnels account. Setup asks
for the file path and authentication provider. You can supply them explicitly:

```bash
./setup-hkstp.sh --name bob-codex --connection /path/to/connection.env --provider github
./setup-hkstp.sh --name bob-codex --defer-egress  # install now, connect later
./setup-hkstp.sh --help
```

`--skip-login` skips Codex login only; egress still needs valid Dev Tunnels
authentication. `--codex-version X.Y.Z` selects another official npm release.
Setup requires Linux, Python 3.8+, Bash, Git and curl. It reuses available Node/npm,
tmux and Dev Tunnels. Missing Node/npm are installed from a checksum-verified
Node 22 LTS archive (tar/xz required); missing tmux is installed with Conda
(`CONDA_EXE` is supported); missing Dev Tunnels is downloaded from Microsoft into
the person's tools directory. If neither tmux nor Conda is available, install
tmux first. Dev Tunnels needs a compatible ICU runtime; if its version check
fails, install ICU or provide a working `devtunnel` on PATH before rerunning.
GOST is required on the laptop/VPS host, not on the cluster client.

The pinned egress client forwards the **host's chosen port** to the same port on
the cluster. Setup checks for conflicts and never stops somebody else's tunnel
to free a port. If a port is occupied, stop your laptop/VPS host, move its
`connection.env` aside, and restart the host to generate a new tunnel and port.
Copy that new file to the cluster and rerun setup with `--connection`. To replace
an existing connection, first stop your own client with `bob-codex --egress stop`.
Do not edit only one copy's port: the host and cluster configurations must match.

After an abrupt process kill, the pinned client may leave
`.hkstp/egress/.connect.lock`. Inspect `bob-codex --egress logs`; remove that
directory only after verifying that this person's client and supervisor have
stopped. Normal `--egress stop` cleans up the lock.
