# Direct VPS egress for Codex and Claude

This guide routes agent HTTP traffic from a WebStudio container through an
authenticated HTTPS proxy on a VPS. It covers both a **new Ubuntu VPS without
Coolify** and the existing Oracle Cloud VPS with Coolify. The direct route does
not use Microsoft Dev Tunnels for new agent connections. It does not provide VS
Code editor access or a system-wide VPN.

For the recommended two-part setup on a fresh VPS, including **without a
domain**, see [the containerized VPS + WebStudio guide](vps-bootstrap.md).
GOST and certificate issuance/renewal run in isolated containers. The manual
hostname-based recipes below remain available as alternative deployments.

## Traffic path

```text
Codex / Claude launched by webstudio-utils
  -> HTTP_PROXY=http://127.0.0.1:<temporary-port>
  -> short-lived GOST client on WebStudio
  -> verified TLS to proxy.example.com:443
  -> authenticated GOST proxy on the VPS
  -> official OpenAI / Anthropic endpoint
```

The local HTTP proxy is bound only to WebStudio's loopback interface. GOST
authenticates to the VPS proxy and verifies the VPS certificate and hostname.
On a new VPS, GOST terminates TLS itself. On the Coolify VPS, Traefik terminates
TLS and forwards proxy traffic to GOST over the private Docker network. For
HTTPS destinations, the agent still uses HTTP
`CONNECT`, and its TLS connection to the destination remains end to end.
Use a DNS A record pointing to the VPS. If the domain uses Cloudflare, select
**DNS only** so proxy traffic goes directly to the VPS.

Use port **443**, which was reachable directly from the tested WebStudio
environment. On a new VPS, GOST can own that port. On a VPS where a web server
already owns it, use a hostname-specific TCP TLS router as in the Coolify
example below. Check your own WebStudio network's outbound rules first.

## New VPS without Coolify

This example assumes a fresh Ubuntu VPS with a public IPv4 address, SSH access,
and no service already listening on ports 80 or 443. It also assumes you control
`proxy.example.com`; replace that name and `admin@example.com` throughout.
Other Linux distributions need equivalent package and service commands. A
hostname with a publicly trusted certificate is needed for the documented
client configuration.

1. **Prepare networking and DNS.** In the cloud provider's security group or
   network firewall, allow inbound TCP 443 for the proxy and TCP 80 for the
   certificate authority's HTTP challenge. Allow outbound HTTPS and access to
   the upstream APIs. Keep SSH access enabled for administration. If the VPS
   also has a host firewall, allow 80 and 443 there. Create an A record for
   `proxy.example.com` pointing to the VPS public IPv4 address. In Cloudflare,
   set that record to **DNS only** (grey cloud). Wait until
   `getent ahostsv4 proxy.example.com` returns the VPS address. TCP 80 must be
   reachable from the public internet for the certificate step below; if that
   is impossible, use a DNS challenge with your certificate issuer instead.

2. **Install GOST and Certbot.** These commands use the same GOST v3.3.3 version
   as the WebStudio client and verify the release archive before installing it.
   Run them on the VPS:

   ```bash
   set -e
   sudo apt update
   sudo apt install -y ca-certificates curl tar certbot
   version=3.3.3
   case "$(uname -m)" in
     x86_64) arch=amd64 ;;
     aarch64|arm64) arch=arm64 ;;
     *) echo 'Use a supported GOST release asset for this CPU' >&2; exit 1 ;;
   esac
   asset="gost_${version}_linux_${arch}.tar.gz"
   workdir="$(mktemp -d)"
   cd "$workdir"
   curl -fL -o "$asset" "https://github.com/go-gost/gost/releases/download/v${version}/${asset}"
   curl -fL -o checksums.txt "https://github.com/go-gost/gost/releases/download/v${version}/checksums.txt"
   grep -F "  $asset" checksums.txt | sha256sum -c -
   tar -xzf "$asset" gost
   sudo install -m 755 gost /usr/local/bin/gost
   gost -V
   ```

   Stop if the checksum does not match. The downloaded archive and temporary
   directory can be removed after installation.

3. **Issue a certificate.** Do this after DNS and port 80 work. The standalone
   Certbot authenticator listens on port 80 during validation:

   ```bash
   sudo certbot certonly --standalone --non-interactive --agree-tos \
     -m admin@example.com -d proxy.example.com
   ```

   The resulting certificate and key are under
   `/etc/letsencrypt/live/proxy.example.com/`. If another service already owns
   port 80, arrange a different certificate challenge before running this step.

4. **Create private proxy credentials and configuration.** The
   [standalone template](../examples/gost-standalone-vps.yaml) shows the GOST
   format. Run this on the VPS after replacing the hostname in the Python
   snippet. It creates a random password without putting it in shell history:

   ```bash
   sudo python3 - <<'PY'
   from pathlib import Path
   from urllib.parse import quote
   import os
   import secrets

   hostname = 'proxy.example.com'  # Replace with your DNS name.
   directory = Path('/etc/gost')
   directory.mkdir(mode=0o700, exist_ok=True)
   server = directory / 'egress.yaml'
   client = directory / 'client-url'
   if server.exists() or client.exists():
       raise SystemExit('Existing proxy credentials found; preserve them')
   password = secrets.token_hex(24)
   server.write_text(
       'services:\n'
       '  - name: webstudio-egress\n'
       '    addr: ":443"\n'
       '    handler:\n'
       '      type: http\n'
       '      auth:\n'
       '        username: codexproxy\n'
       f'        password: {password}\n'
       '    listener:\n'
       '      type: tls\n'
       '      tls:\n'
       f'        certFile: /etc/letsencrypt/live/{hostname}/fullchain.pem\n'
       f'        keyFile: /etc/letsencrypt/live/{hostname}/privkey.pem\n'
   )
   client.write_text(
       f'https://codexproxy:{quote(password)}@{hostname}:443\n'
   )
   os.chmod(server, 0o600)
   os.chmod(client, 0o600)
   PY
   ```

   Keep `/etc/gost/client-url` private. Copy its single line to the hidden
   WebStudio configuration prompt below using a secure channel. Do not commit
   either private file.

5. **Run the proxy at boot.** This simple systemd service runs as root so it
   can bind port 443 and read the private certificate key. On the VPS:

   ```bash
   sudo tee /etc/systemd/system/gost-egress.service >/dev/null <<'UNIT'
   [Unit]
   Description=Authenticated HTTPS egress proxy
   Wants=network-online.target
   After=network-online.target

   [Service]
   Type=simple
   ExecStart=/usr/local/bin/gost -C /etc/gost/egress.yaml
   Restart=on-failure
   RestartSec=5
   NoNewPrivileges=true
   PrivateTmp=true

   [Install]
   WantedBy=multi-user.target
   UNIT
   sudo systemctl daemon-reload
   sudo systemctl enable --now gost-egress.service
   sudo systemctl status gost-egress.service
   ```

6. **Reload GOST after certificate renewal.** Certbot's deploy hook runs after
   a successful renewal, so GOST can read the renewed files. The distribution
   should also enable a Certbot timer or equivalent scheduled renewal; verify
   it with `systemctl list-timers '*certbot*'`:

   ```bash
   sudo install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
   sudo tee /etc/letsencrypt/renewal-hooks/deploy/restart-gost-egress >/dev/null <<'HOOK'
   #!/bin/sh
   exec systemctl restart gost-egress.service
   HOOK
   sudo chmod 755 /etc/letsencrypt/renewal-hooks/deploy/restart-gost-egress
   sudo certbot renew --dry-run
   ```

   The dry run tests certificate renewal; it does not run deploy hooks by
   default. Confirm `systemctl is-active gost-egress.service` is `active` and
   continue with the WebStudio check below. Once this path works, later
   renewals run automatically if the Certbot timer is enabled.

This path needs no Docker, Coolify, or Traefik. The same VPS can serve multiple
clients if each knows the proxy credentials; rotate the password if it is
exposed. Restrict port 443 to known WebStudio source IPs only when those IPs are
stable and you can maintain the allowlist.

## Coolify VPS example

This variant shares Coolify's public port 443 with existing websites. Replace
the example hostname with your own DNS name. The proxy password and client URL
belong only in private files on the VPS and WebStudio container.

| Part | Example value |
| --- | --- |
| DNS A record | `proxy.example.com` -> VPS public IPv4 address, **DNS only** if using Cloudflare |
| Public TLS entry | Coolify's Traefik on TCP 443; Let's Encrypt certificate for `proxy.example.com` |
| VPS proxy | Docker container `webstudio-direct-egress` on the `coolify` network, internal port 8080 |
| VPS private files | `$HOME/.config/webstudio-direct-egress/gost.yaml` and `client-url` |
| WebStudio credentials | `$WEBSTUDIO_AGENT_STATE_DIR/egress/direct-proxy.json`, mode 600 |
| WebStudio client binary | `$WEBSTUDIO_PERSIST_ROOT/tools/gost/3.3.3/bin/gost` |
| Verified archive cache | `$WEBSTUDIO_PERSIST_ROOT/cache/gost/` |

The VPS container has Docker's `unless-stopped` restart policy. Traefik's
`letsencrypt` resolver obtains and renews the certificate through its HTTP
challenge on port 80; this variant does not need a separate Certbot
service or Cloudflare Origin Certificate. The proxy rejects requests without
GOST credentials (`407 Proxy Authentication Required`). Its private files and
the WebStudio credential file must not be committed.

The older Dev Tunnels egress host and its loopback GOST process were left
running. The new Docker container is separate. A running Codex process keeps
the route it started with; only a newly launched process selects direct egress.
Do not stop the old tunnel while a session still uses it. The VS Code Remote
Tunnel is another, separate service; direct agent egress does not replace editor
access.

### Rebuild the Coolify VPS side

These steps assume an existing Coolify installation and an unprivileged SSH
user with access to Docker through `sudo`. If replacing an existing proxy
container, preserve its private configuration and plan the replacement before
running `docker run` again.

1. In Cloudflare DNS, create an A record named `egress` pointing to the VPS
   public IP. Set **Proxy status: DNS only** (grey cloud). Keep existing website
   records as they are. Create DNS before starting the proxy so
   Let's Encrypt can validate the hostname on its first attempt.
2. Confirm that Coolify's Traefik uses entry points named `http` on port 80 and
   `https` on port 443, has a `letsencrypt` certificate resolver, and that the
   `coolify` Docker network exists. Those names appear in the container labels
   below. Port 443 must be reachable from WebStudio, and port 80 must remain
   reachable for Traefik's HTTP certificate challenge.
3. Install GOST v3 on the VPS using the checksum-verified download in the
   standalone instructions above, then place its binary at
   `$HOME/.local/bin/gost`:

   ```bash
   install -d -m 755 "$HOME/.local/bin"
   install -m 755 /usr/local/bin/gost "$HOME/.local/bin/gost"
   "$HOME/.local/bin/gost" -V
   ```

   The public GOST listener is separate from any old loopback GOST used by Dev
   Tunnels.
4. Generate a separate long password and private GOST configuration. The
   checked-in [configuration example](../examples/gost-direct-vps.yaml) shows
   the format. Replace `proxy.example.com` in the Python snippet and Docker
   labels with your DNS name. The following creates both the server
   configuration and the client URL without putting the password in shell
   history:

   ```bash
   install -d -m 700 "$HOME/.config/webstudio-direct-egress"
   python3 - <<'PY'
   from pathlib import Path
   import os
   import secrets

   directory = Path.home() / '.config/webstudio-direct-egress'
   server = directory / 'gost.yaml'
   client = directory / 'client-url'
   if server.exists() or client.exists():
       raise SystemExit('Existing proxy credentials found; preserve them')
   password = secrets.token_hex(24)
   server.write_text(
       'services:\n'
       '  - name: webstudio-direct-egress\n'
       '    addr: ":8080"\n'
       '    handler:\n'
       '      type: http\n'
       '      auth:\n'
       '        username: codexproxy\n'
       f'        password: {password}\n'
       '    listener:\n'
       '      type: tcp\n'
   )
   client.write_text(
       f'https://codexproxy:{password}@proxy.example.com:443\n'
   )
   os.chmod(server, 0o600)
   os.chmod(client, 0o600)
   PY
   ```

5. Start GOST in a separate container on the `coolify` network. Run this as
   the same SSH user who owns the private configuration. The container does
   **not** publish its internal port to the host:

   ```bash
   sudo docker run -d --name webstudio-direct-egress --network coolify \
     --restart unless-stopped --user "$(id -u):$(id -g)" --read-only \
     --cap-drop ALL --security-opt no-new-privileges \
     --mount "type=bind,src=$HOME/.local/bin/gost,dst=/usr/local/bin/gost,readonly" \
     --mount "type=bind,src=$HOME/.config/webstudio-direct-egress/gost.yaml,dst=/etc/gost.yaml,readonly" \
     --label traefik.enable=true \
     --label 'traefik.tcp.routers.webstudio-egress.rule=HostSNI(`proxy.example.com`)' \
     --label traefik.tcp.routers.webstudio-egress.entrypoints=https \
     --label traefik.tcp.routers.webstudio-egress.tls=true \
     --label traefik.tcp.routers.webstudio-egress.tls.certresolver=letsencrypt \
     --label traefik.tcp.routers.webstudio-egress.tls.domains[0].main=proxy.example.com \
     --label traefik.tcp.routers.webstudio-egress.service=webstudio-egress \
     --label traefik.tcp.services.webstudio-egress.loadbalancer.server.port=8080 \
     busybox:musl /usr/local/bin/gost -C /etc/gost.yaml
   ```

   Traefik discovers those Docker labels. Its TCP router matches only the proxy
   hostname, terminates TLS, and forwards to the authenticated GOST service.
   Website hostnames continue to use their existing HTTP routes. GOST's
   internal HTTP connection is confined to the VPS's Docker network; other
   containers attached to that network can reach the port, so authentication
   remains necessary there too.

## Configure the WebStudio side

For a fresh agent installation without a VS Code Remote Tunnel:

```bash
cd /path/to/webstudio-utils
./setup_tools.sh --agents codex --official --skip-vscode --direct-egress
source shell/init.sh
```

At the hidden prompt, enter the complete URL from the VPS's private
`client-url` file. Transfer that file securely. Do not paste its password into
shell commands, Git, or issue trackers. `--skip-vscode` avoids VS Code tunnel
installation and startup and saves a preference that suppresses later shell
prompts to start it. Rerun setup without `--skip-vscode` to restore those
prompts. Choose `--agents both` if Claude should also be installed.

For an existing installation, configure the proxy without reinstalling agents:

```bash
cd /path/to/webstudio-utils
source shell/init.sh
python3 scripts/direct_egress.py configure
python3 scripts/direct_egress.py check && echo 'VPS proxy OK'
```

The `configure` prompt hides input and atomically writes the URL to
`$WEBSTUDIO_AGENT_STATE_DIR/egress/direct-proxy.json` with mode 600. Setup also
installs a checksum-verified GOST v3.3.3 client under persistent `tools/gost/`
and caches the compressed archive under `cache/gost/`. On an existing install,
run `python3 scripts/install_direct_gost.py` once if the binary is missing.
Temporary per-agent GOST configuration lives in `$WEBSTUDIO_LOCAL_DIR` (normally
`/tmp/webstudio-$UID`) and is removed when that agent exits.

The [agent launcher](../scripts/agent-launch.sh) prefers `direct-proxy.json`
when present. It checks the direct proxy before automatic selection, then starts
the local GOST client for the agent process. `HTTP_PROXY` and `HTTPS_PROXY` are
set for that process and its children; the parent shell's proxy settings are
not changed. The local `http://` address is compatible with Codex's WebSocket
transport, while GOST carries it to the VPS over verified TLS. If the GOST
binary is missing, the launcher can use the `https://` proxy directly, but
some Codex versions retry WebSockets before falling back to HTTPS.

## Verify and use

On a standalone VPS, check the systemd service. On the Coolify VPS, check the
container instead:

```bash
# Standalone VPS:
sudo systemctl is-active gost-egress.service
sudo journalctl -u gost-egress.service -n 30 --no-pager

# Coolify VPS:
sudo docker inspect webstudio-direct-egress --format '{{.State.Status}} {{.HostConfig.RestartPolicy.Name}}'
sudo docker logs --tail 30 webstudio-direct-egress
```

From WebStudio, verify the proxy and start a new Codex process:

```bash
cd /path/to/webstudio-utils
source shell/init.sh
python3 scripts/direct_egress.py check && echo 'VPS proxy OK'
codex --provider official login status
codex
```

The launcher prints `Using direct VPS egress · official authentication`.
`login status` checks the saved Codex authentication and launch route; it is
not an end-to-end model request. For this deployment, a real `codex exec`
request also completed through the VPS, and a separate proxy test returned
the VPS's public IP. A TLS verification failure is not bypassed in normal use.

## Failure and switching routes

- If the proxy check fails, verify DNS resolves to the VPS, the certificate
  covers the proxy hostname, TCP 443 reaches the VPS, and the WebStudio URL has
  the matching password. On a standalone VPS, inspect `journalctl -u
  gost-egress.service` and confirm the certificate files are readable by the
  service. On Coolify, check Traefik's TCP router, the proxy container, and
  `sudo docker logs coolify-proxy` for ACME errors. A first certificate attempt
  made before DNS existed can fail with NXDOMAIN; create the record and retry
  issuance. Do not restart Coolify or the old tunnel just to debug this proxy.
- An unreachable configured direct proxy makes automatic agent launches fail
  instead of silently sending traffic elsewhere. The separate OpenLux backup
  is available with `codex --provider openlux` when configured.
- To return future launches to the old Dev Tunnels egress, move
  `direct-proxy.json` out of the egress state directory and keep the old
  `connection.env` and tunnel available. A running agent does not switch routes
  mid-session. Reconfigure direct mode with `python3 scripts/direct_egress.py
  configure` when ready.
- If Coolify recreates its Docker network, verify that
  `webstudio-direct-egress` is still attached to `coolify`. The proxy container
  can be replaced without changing the older tunnel host. Preserve the VPS
  `gost.yaml` and `client-url` files when doing so.

## Upstream references

- [Cloudflare DNS-only and proxied records](https://developers.cloudflare.com/learning-paths/prevent-ddos-attacks/baseline/proxy-dns-records/)
- [Traefik TCP routers and TLS certificate resolvers](https://doc.traefik.io/traefik/reference/routing-configuration/tcp/routing/router/)
- [GOST authentication](https://v3.gost.run/en/concepts/auth/) and [TLS settings](https://v3.gost.run/en/tutorials/tls/)
- [GOST v3.3.3 release assets and checksums](https://github.com/go-gost/gost/releases/tag/v3.3.3)
- [Certbot standalone validation and renewal hooks](https://eff-certbot.readthedocs.io/en/stable/using.html)
