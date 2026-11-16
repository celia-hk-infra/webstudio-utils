#!/usr/bin/env python3
"""Run agents through an authenticated HTTPS proxy on a user-owned VPS."""
import getpass
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit


def config_path():
    state = Path(os.environ["WEBSTUDIO_AGENT_STATE_DIR"]) / "egress"
    return state / "direct-proxy.json"


def valid_url(value):
    if not isinstance(value, str):
        raise ValueError("Invalid proxy URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        username, password = parsed.username, parsed.password
    except ValueError as error:
        raise ValueError("Invalid proxy URL") from error
    if (parsed.scheme != "https" or not parsed.hostname or not username or
            not password or not port or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("Expected https://user:password@host:port")
    return value


def read_url(path):
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("Proxy configuration must be private (chmod 600)")
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != {"proxy_url"}:
        raise ValueError("Invalid proxy configuration")
    return valid_url(data["proxy_url"])


def proxy_environment(url):
    env = os.environ.copy()
    for name in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env.pop(name, None)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env[name] = url
    env["NO_PROXY"] = env["no_proxy"] = "localhost,127.0.0.1,::1"
    return env


def gost_binary():
    override = os.environ.get("WEBSTUDIO_GOST_BIN")
    if override:
        return Path(override)
    state = Path(os.environ["WEBSTUDIO_AGENT_STATE_DIR"])
    root = Path(os.environ.get("WEBSTUDIO_PERSIST_ROOT", str(state.parent)))
    return root / "tools/gost/3.3.3/bin/gost"


def gost_config(url, port):
    proxy = urlsplit(url)
    return {
        "services": [{
            "name": "webstudio-local-proxy",
            "addr": f"127.0.0.1:{port}",
            "handler": {"type": "http", "chain": "vps"},
            "listener": {"type": "tcp"},
        }],
        "chains": [{
            "name": "vps",
            "hops": [{
                "name": "vps-hop",
                "nodes": [{
                    "name": "vps-node",
                    "addr": f"{proxy.hostname}:{proxy.port}",
                    "connector": {"type": "http", "auth": {
                        "username": unquote(proxy.username),
                        "password": unquote(proxy.password),
                    }},
                    "dialer": {"type": "tls", "tls": {
                        "secure": True,
                        "serverName": proxy.hostname,
                    }},
                }],
            }],
        }],
    }


def run_with_gost(url, command):
    binary = gost_binary()
    if not binary.is_file():
        # HTTPS requests still work directly; older Codex WebSocket clients
        # may retry before falling back to HTTPS until GOST is installed.
        os.execvpe(command[0], command, proxy_environment(url))
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    local = Path(os.environ.get("WEBSTUDIO_LOCAL_DIR", f"/tmp/webstudio-{os.getuid()}"))
    local.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(local, 0o700)
    fd, path = tempfile.mkstemp(prefix=".direct-gost-", suffix=".json", dir=local)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(gost_config(url, port), output)
        os.chmod(path, 0o600)
        process = subprocess.Popen([str(binary), "-C", path],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                if process.poll() is not None:
                    raise RuntimeError("Local GOST proxy exited during startup")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Local GOST proxy did not start")
            env = proxy_environment(f"http://127.0.0.1:{port}")
            try:
                return subprocess.run(command, env=env, check=False).returncode
            except KeyboardInterrupt:
                return 130
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    finally:
        Path(path).unlink(missing_ok=True)


def check(env):
    for attempt in range(3):
        result = subprocess.run(
            ["curl", "-q", "--fail", "--silent", "--show-error", "--connect-timeout", "5",
             "--max-time", "15", "https://api.ipify.org"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0 or attempt == 2:
            return result.returncode
        time.sleep(1)


def configure(path):
    url = valid_url(getpass.getpass("VPS HTTPS proxy URL: ").strip())
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, staged = tempfile.mkstemp(prefix=".direct-proxy.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump({"proxy_url": url}, output)
            output.write("\n")
        os.chmod(staged, 0o600)
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)
    print(f"Saved private proxy configuration: {path}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("configure", "check", "exec"):
        print("Usage: direct_egress.py {configure|check|exec COMMAND...}", file=sys.stderr)
        return 2
    command = sys.argv[1]
    path = config_path()
    try:
        if command == "configure":
            if len(sys.argv) != 2:
                return 2
            configure(path)
            return 0
        url = read_url(path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Direct egress: {error}", file=sys.stderr)
        return 2
    env = proxy_environment(url)
    if command == "check":
        if len(sys.argv) != 2:
            return 2
        try:
            return check(env)
        except OSError as error:
            print(f"Direct egress: {error}", file=sys.stderr)
            return 1
    if len(sys.argv) < 3:
        return 2
    try:
        return run_with_gost(url, sys.argv[2:])
    except (OSError, RuntimeError) as error:
        print(f"Direct egress: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
