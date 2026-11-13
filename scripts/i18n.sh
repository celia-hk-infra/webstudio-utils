#!/usr/bin/env bash
# Translate shared UI text, preserving paths, versions and command examples.
ui_text() {
  local text=$1 english chinese
  local -a originals=() translations=()
  local i
  if [[ ${WEBSTUDIO_LANGUAGE:-en} == zh ]]; then
    while IFS='|' read -r english chinese; do
      [[ -n $english ]] || continue
      if [[ $text == "$english" ]]; then printf '%s' "$chinese"; return; fi
      originals+=("$english"); translations+=("$chinese")
    done <<'TRANSLATIONS'
Which coding agents should be installed?|请选择要安装的编程助手
Which optional tools should be installed?|请选择要安装的可选工具
Terminal sessions and background VS Code tunnels|终端会话及后台 VS Code 隧道
gh commands and GitHub authentication|gh 命令及 GitHub 身份验证
Coding agents|编程助手
Optional tools|可选工具
None (tools only)|不安装（仅工具）
None|无
WebStudio tools setup|WebStudio 工具安装
Safe to rerun; answers are saved|可安全重复运行；配置会保存
Start the VS Code tunnel when setup finishes?|安装完成后是否启动 VS Code 隧道？
In the background (tmux session vscode-tunnel)|在后台运行（tmux 会话 vscode-tunnel）
keeps running after you close this terminal (recommended)|关闭终端后继续运行（推荐）
shows tunnel logs here; Ctrl+C stops it|在此显示日志；Ctrl+C 停止
start it later with scripts/start_vscode_tunnel.sh|稍后通过 scripts/start_vscode_tunnel.sh 启动
In the background|在后台运行
In this terminal|在当前终端运行
Not now|暂不启动
Start VS Code tunnel|启动 VS Code 隧道
VS Code tunnel name|VS Code 隧道名称
Enter keeps |直接回车保留 
; letters, digits, hyphens|；仅限字母、数字、连字符
must start with a letter or digit|必须以字母或数字开头
Installing GitHub CLI|正在安装 GitHub CLI
Installing tmux with Conda|正在通过 Conda 安装 tmux
Installing Claude Code|正在安装 Claude Code
Installing Codex|正在安装 Codex
Installing the VS Code tunnel CLI|正在安装 VS Code 隧道 CLI
Installing|正在安装
Sign in to GitHub.|登录 GitHub
The token is stored in the private persistent gh directory.|令牌保存在私有的持久化 gh 目录中。
Open https://github.com/login/device in your browser and enter the code below. Setup continues automatically.|请在浏览器打开 https://github.com/login/device 并输入下方代码。授权后安装会自动继续。
GitHub authentication ready|GitHub 身份验证已就绪
Git uses gh for HTTPS credentials|Git 使用 gh 提供 HTTPS 凭据
Configure personal egress now? [y/N] |现在配置个人网络出口吗？[y/N] 
Configure OpenLux as an optional backup? [y/N] |配置 OpenLux 作为可选备用服务吗？[y/N] 
Sign in to official Codex through egress now? [y/N] |现在通过个人出口登录官方 Codex 吗？[y/N] 
Sign in to official Claude through egress now? [y/N] |现在通过个人出口登录官方 Claude 吗？[y/N] 
OpenLux API key|OpenLux API 密钥
(input hidden; Enter keeps saved credentials)|(输入隐藏；回车保留已保存的凭据)
(input hidden)|(输入隐藏)
Saved for the selected agents (|已为所选助手保存（
 characters)| 个字符）
Keeping saved credentials|保留已保存的凭据
A key is required for the selected agents|所选助手需要 API 密钥
Saving the OpenLux key for Codex|正在保存 Codex 的 OpenLux 密钥
 ready| 已就绪
VS Code tunnel CLI ready|VS Code 隧道 CLI 已就绪
tunnel name: |隧道名称：
Agents     |编程助手   
Tools      |工具       
Tunnel     |隧道       
Storage    |存储位置   
Setup log  |安装日志   
New terminals load the environment automatically.|新终端会自动加载环境。
In this terminal, run first:|在当前终端中，请先运行：
Start VS Code later:|稍后启动 VS Code：
Setup complete|安装完成
Keep this terminal open while using the tunnel. Ctrl+C stops it.|使用隧道时请保持此终端打开，Ctrl+C 停止。
Sign in to authorize the VS Code tunnel|登录以授权 VS Code 隧道
Open the link below and enter the code. The sign-in is kept in this container's tunnel directory.|打开下方链接并输入代码。登录凭据保存在本容器的隧道目录中。
VS Code tunnel is running in the background|VS Code 隧道正在后台运行
VS Code tunnel is already running|VS Code 隧道已在运行
Done|完成
Please enter y or n.|请输入 y 或 n。
↑/↓ move · space toggle · a all · enter confirm · q cancel|↑/↓ 移动 · 空格切换 · a 全选 · 回车确认 · q 取消
↑/↓ move · enter select · q cancel|↑/↓ 移动 · 回车选择 · q 取消
Personal egress|个人网络出口
Preparing pinned egress tools|正在准备固定版本的出口工具
Installing Microsoft Dev Tunnels|正在安装 Microsoft Dev Tunnels
On your laptop/Mac/VPS, clone this repository and start the egress host:|在笔记本、Mac 或 VPS 上克隆本仓库并启动网络出口：
Install GOST v3, Python 3 and Dev Tunnels first; see vendor/codex-local-egress/README.md.|请先安装 GOST v3、Python 3 和 Dev Tunnels；参见 vendor/codex-local-egress/README.md。
Keep it running. Copy connection.env from vendor/codex-local-egress, or paste its three lines below.|保持其运行。复制 vendor/codex-local-egress 下的 connection.env，或在下方粘贴其中的三行。
Both endpoints must sign in with the same Dev Tunnels account.|两端必须使用同一个 Dev Tunnels 账号登录。
Path to connection.env (Enter to paste; type skip to defer): |connection.env 路径（回车粘贴；输入 skip 跳过）：
File not found; enter an absolute path or a path relative to this terminal.|文件不存在；请输入绝对路径或相对于当前终端的路径。
Paste the three lines; finish with an empty line (input hidden).|请粘贴三行配置，以空行结束（输入隐藏）。
Dev Tunnels login provider|Dev Tunnels 登录方式
Sign in using the same account as your laptop/VPS. Open the URL and enter the code shown below.|请使用与笔记本或 VPS 相同的账号登录。打开下方网址并输入代码。
Personal egress ready. Use codex login or claude auth login after setup.|个人出口已就绪。安装后可使用 codex login 或 claude auth login 登录。
Egress not ready. Inspect: tmux attach -t webstudio-egress|出口尚未就绪。请检查：tmux attach -t webstudio-egress
An existing egress session uses different settings. Stop that session deliberately before replacing them.|现有出口会话正在使用不同配置。请先手动停止该会话再替换配置。
Install tmux or run remote.sh manually to connect egress.|请安装 tmux，或手动运行 remote.sh 连接出口。
Using personal egress · official authentication|使用个人出口 · 官方身份验证
Checking personal egress...|正在检查个人出口…
Open|打开
Logs   |日志   
Stop   |停止   
(detach: Ctrl+B, then D)|(退出查看：Ctrl+B，然后 D)
maximum |最多 
 characters| 个字符
 is not allowed| 不允许输入
Setup cancelled.|安装已取消。
TRANSLATIONS
    for i in "${!originals[@]}"; do
      text=${text//"${originals[i]}"/"${translations[i]}"}
    done
  fi
  printf '%s' "$text"
}
