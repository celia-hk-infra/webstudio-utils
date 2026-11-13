"""Present vendor authentication output without banners or browser prompts."""
import re
import sys

zh = len(sys.argv) > 1 and sys.argv[1] == 'zh'
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    match = re.search(r'(https://\S+).*?(?:code:|code)\s*([A-Z0-9-]+)', line)
    if match:
        line = (f'请打开 {match[1]} 并输入代码：{match[2]}' if zh
                else f'Open {match[1]} and enter code: {match[2]}')
    elif 'one-time code:' in line:
        code = line.split('one-time code:', 1)[1].strip()
        line = ('授权代码：' if zh else 'Device code: ') + code
    elif line.startswith('Logged in as '):
        if zh:
            line = '登录成功：' + line.removeprefix('Logged in as ')
    elif line.startswith(('Welcome to dev tunnels!', 'CLI version:', 'By using the software', '- the dev tunnels', '- the Microsoft Privacy', 'Report issues on GitHub:', "Use 'devtunnel --help'", 'Press Enter to open', '! Failed to copy', 'No clipboard utilities', '! Did you know')):
        continue
    print('│  ' + line, flush=True)
