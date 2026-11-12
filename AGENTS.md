# Repository context

This repository sets up development tools and VS Code Remote Tunnels on
disposable WebStudio/ModelArts Linux containers backed by persistent SFS/NFS
storage. The intended workflow is to install once on SFS, then reuse tools and
user data when a container restarts or is replaced.

## Storage design and rationale

- `WEBSTUDIO_PERSIST_ROOT` defaults to this repository's parent directory.
  Tool installations and download caches live under `tools/` and `cache/`.
- `WEBSTUDIO_AGENT_STATE_DIR` defaults to
  `$WEBSTUDIO_PERSIST_ROOT/.webstudio-agent-home`. It contains private persistent
  user state, including VS Code remote settings and extensions in `vscode-server/`.
- `WEBSTUDIO_LOCAL_DIR` defaults to `/tmp/webstudio-$UID`. In the environment
  where this layout was developed, `/home/ma-user/work` is NFS and `/tmp` is local
  container storage. Do not assume that a directory named `work` is local disk;
  check its filesystem before changing this layout.
- Keep extracted VS Code server binaries and download staging on local disk.
  The server contains thousands of files, and NFS metadata operations add
  startup and module-loading latency. Local files are disposable: retain the
  compressed installation archives on persistent storage so they can be
  extracted again without another network download.
- Keep settings, remote extensions, and other user data on persistent storage.
  Do not move these back into `/tmp` to improve executable startup performance.
- Tunnel identity is separate from portable editor data. `WEBSTUDIO_TUNNEL_DIR`
  defaults to `/home/ma-user/work/.webstudio-tunnel` and contains the name and
  CLI credentials. Its survival depends on retention of that container's work
  directory; the path is not a guarantee of either local disk or persistence
  across replacement containers. Do not share a tunnel identity between active
  containers. Concurrent containers should also use separate editor data
  directories via `VSCODE_PERSISTENT_DATA_DIR`; archive caches may be shared.

## Tunnel installation and startup

- `setup_tools.sh` handles tool selection, installation, and the completion
  marker. It calls `scripts/start_vscode_tunnel.sh --install-only`, which installs
  the compatibility runtime and standalone CLI and prefetches the latest stable
  server archive. The server is extracted on demand by VS Code.
- `shell/init.sh` restores environment variables, paths, and shell hooks. An
  interactive shell may offer to resume the tunnel. This is not a system service
  and does not guarantee unattended startup after a reboot.
- `scripts/start_vscode_tunnel.sh --background` authenticates before detaching
  and runs the tunnel in the `vscode-tunnel` tmux session. The download helper
  wraps the CLI process. Foreground mode uses the same helper.
- `--server-data-dir` does not control where the CLI installs server binaries.
  The launcher links `cli-data/servers` to the local `vscode/servers` directory
  and explicitly supplies persistent server-data and extensions directories.
- A tunnel reporting `Connected` only confirms its relay connection. Verify
  editor-server startup separately when diagnosing an unusable remote session.
  The editor server and agent supervisor can request different server versions.

## Download acceleration

Single-connection server downloads in this environment have been slow enough
to delay first connections for tens of minutes and exceed supervisor startup
timeouts. `scripts/vscode_downloads.py` addresses this through the CLI's
`VSCODE_CLI_UPDATE_URL` override: a loopback update service handles the exact
commit/platform/channel requested by each client, including versions that were
not prefetched during setup.

The helper uses up to 32 parallel range requests by default, validates response
ranges and sizes, verifies Microsoft's SHA-256 checksum, and atomically publishes
archives into `$VSCODE_INSTALL_DIR/server-archives`. Cache hits are checksum
verified and served locally. Range-unsupported servers fall back to a verified
single download. Preserve verification and atomic publication when changing this
code; never expose incomplete downloads as valid cache entries.

`--prefetch` refreshes the latest stable archive cache. Older or newer client
versions are handled on demand. The small standalone CLI archive is cached
separately and currently uses ordinary curl; it is reused rather than
automatically upgraded on each setup run. Parallel downloads improve this
environment's observed bottleneck but cannot guarantee external network speed.
Old server archives are retained; there is currently no automatic cache eviction.

## Persistence and migration

The helper migrates an older local `server-data` directory to persistent storage,
keeps a recovery copy, and replaces the old path with a symlink. It refuses to
migrate data used by a running editor or overwrite a conflicting destination.
Preserve these protections and existing user data during future migrations.

Container termination still ends terminals, commands, debuggers, and tmux
sessions. Persistent editor data does not preserve running processes or promise
recovery of every unsaved buffer. Stopping the tunnel can leave detached VS Code
processes alive; check for those before migrating editor databases.

## Validation and maintenance

Run `python3 -m unittest discover -s tests -v` for the setup and download tests,
`bash -n scripts/start_vscode_tunnel.sh` for launcher syntax, and
`git diff --check` before committing changes. Tests use isolated temporary
directories and a local HTTP origin, with no real credentials or downloads.

For download or CLI-integration changes, supplement the tests with a targeted
live check when appropriate: verify checksum completion, restoration into an
empty local server directory from persistent cache, and actual server startup.
Avoid restarting an active user's editor merely to repeat an already-passing
check. Keep README and launcher help consistent with storage and setup changes.
Never commit credentials, downloaded archives, or generated runtime state.
