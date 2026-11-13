"""Translate pinned host messages while retaining live vendor diagnostics."""
import sys

zh = sys.argv[1] == 'zh'
pairs = '''缺少依赖：|Missing dependency: 
用法：|Usage: 
已有本地服务，或异常退出留下了锁：|A host is running, or a stale lock remains: 
确认没有 local.sh 仍在运行后，再删除此锁目录。|Remove this lock only after confirming local.sh is stopped.
未能选择本地端口。|Unable to choose a local port.
未能生成代理密码。|Unable to generate proxy credentials.
创建持久隧道失败：|Failed to create persistent tunnel: 
未能从 devtunnel create 得到 tunnel id。|No tunnel ID returned by devtunnel create.
tunnel id 无效：|Invalid tunnel ID: 
登记隧道端口失败：|Failed to register tunnel port: 
connection.env 内容无效，没有启动：|Invalid connection.env; host was not started: 
要重新生成，先删除这个文件。|Remove this file to generate a new configuration.
无法确认隧道是否还在：|Unable to verify tunnel: 
这份 connection.env 固定使用该端口。请先释放端口，再重新运行。|This connection.env requires this port. Free the port and retry.
不要改端口，否则远程的 connection.env 会对不上。|Changing the port would invalidate the remote connection.env.
GOST 启动失败：|GOST failed to start: 
本地 GOST 已监听：|GOST is listening on: 
GOST 已开启密码认证。日志：|GOST password authentication enabled. Log: 
下面 host 已有隧道：|Hosting existing tunnel: 
下面 host 新建的持久隧道：|Hosting new persistent tunnel: 
按 Ctrl+C 会停止 host 和 GOST。这条隧道会保留，下次还能用。|Ctrl+C stops the host and GOST. The tunnel remains available for reuse.
devtunnel host 启动失败。|devtunnel host failed to start.
未能从 host 输出确认 tunnel id。配置文件已写好，但先不要复制。|Unable to confirm tunnel ID from host output. Do not copy the configuration yet.
host 仍在运行，输出见终端和：|Host is still running. Output is here and in: 
已沿用连接配置：|Reusing connection configuration: 
端口、密码和 tunnel id 都没变。远程不用再复制 connection.env。|Port, credentials and tunnel ID are unchanged. No need to recopy connection.env.
连接配置已写好：|Connection configuration saved: 
把这一个文件复制到远程仓库目录一次，文件名仍是 connection.env。|Copy this file to the WebStudio container as connection.env.
之后重新运行 local.sh 会沿用同一份，不用再复制。|Future runs reuse this file; no need to copy it again.
原来的隧道已经不存在，这份 connection.env 不能继续用。|The old tunnel no longer exists. The old connection.env cannot be reused.
持久隧道连续 30 天没有活动会被删除。|Persistent tunnels expire after 30 days of inactivity.
已新建持久隧道，并覆盖：|Created a replacement tunnel and updated: 
请把这个新文件再复制到远程仓库目录一次，文件名仍是 connection.env。|Copy this updated file to the WebStudio container as connection.env.
之后就不用每次复制了。|Subsequent runs do not require another copy.
然后在远程仓库目录执行：./remote.sh|Then continue setup_tools.sh on the WebStudio container.
devtunnel host 已退出。|devtunnel host exited.
GOST 已退出，日志：|GOST exited. Log: 
登录缓存目录：|Login cache: 
登录账号：|Login account: 
使用设备码登录。终端接下来会给出网址和代码，在有浏览器的电脑上打开并完成登录。|Open the URL and enter the device code below in your browser.
选择登录账号：|Choose login provider:
请输入 1 或 2：|Enter 1 or 2:
尚未登录，或登录已过期。完成登录后会继续。|Login is missing or expired. Setup resumes after login.
登录未完成。|Login did not complete.
无法确认 devtunnel 登录状态：|Unable to verify Dev Tunnels login:
'''
def messages():
    pending = ''
    while True:
        char = sys.stdin.read(1)
        if not char:
            if pending:
                yield pending
            return
        pending += char
        if char == '\n' or pending.endswith('请输入 1 或 2：'):
            yield pending
            pending = ''


for line in messages():
    if not zh:
        for pair in pairs.splitlines():
            a, b = pair.split('|', 1)
            line = line.replace(a, b)
    else:
        for english, chinese in (
            ('Using personal egress · official authentication', '使用个人出口 · 官方身份验证'),
            ('Checking personal egress...', '正在检查个人出口…'),
            ('Successfully logged in', '登录成功'),
            ('Follow these steps to sign in with ChatGPT using device code authorization:', '请按以下步骤使用设备码登录 ChatGPT：'),
            ('Open this link in your browser and sign in to your account', '在浏览器中打开此链接并登录账号'),
            ('Enter this one-time code (expires in 15 minutes)', '输入此一次性代码（15 分钟后过期）'),
            ('Continue only if you started this login in Codex. If a website or another person gave you this code, cancel.', '仅在您主动发起 Codex 登录时继续。如果代码来自其他人或网站，请取消。'),
            ("OpenAI's command-line coding agent", 'OpenAI 命令行编程助手'),
            ('Welcome to Codex', '欢迎使用 Codex'),
        ):
            line = line.replace(english, chinese)
        line = line.replace('Logged in as ', '登录成功：').replace('Browse to ', '请打开 ').replace(' and enter the code: ', ' 并输入代码：')
    print('│  ' + line.rstrip(), flush=True)
