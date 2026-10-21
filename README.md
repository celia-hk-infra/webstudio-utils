# webstudio-utils

`scripts/start_vscode_tunnel.sh` sources `shell/init.sh` before launching the
VS Code tunnel. The init script keeps common coding-agent directories and global
npm commands under `.webstudio-agent-home` beside this cloned repository, outside
Git. It also links the persistent `shell/.bash_profile` into the container
home for future login Bash shells.

In a JupyterLab terminal, or before launching a different editor, source the
same script yourself:

```bash
source /home/ma-user/work/webstudio-utils/shell/init.sh
```

The container home may be wiped on restart, so run this again from a JupyterLab
terminal after restarting. The VS Code tunnel launcher does it automatically.
The script preserves existing home directories; migrate their contents before
replacing them with links. Set `WEBSTUDIO_AGENT_STATE_DIR` before sourcing to
choose a different persistent state directory. Add another name to the loop in
`shell/init.sh` for an agent that uses a different home directory.
