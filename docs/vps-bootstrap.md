# Two-part setup: containerized VPS proxy and WebStudio client

Run the VPS installer on your VPS, then run the client installer on WebStudio.
Only the **private proxy URL** needs to move between them. No SSH key,
certificate file, or TLS private key needs to be copied to WebStudio.

The VPS installer supports Ubuntu 22.04 or newer with systemd and Python 3,
on ARM64 or x86-64. Use a stable public IPv4 address or a DNS hostname. **A
domain is optional.** This installer is for a dedicated VPS with ports 80 and
443 free. It does not replace Coolify, Traefik, or a previously installed native
GOST service.

## 1. On the VPS

Allow public inbound TCP 80 and 443 in the cloud security list/NSG. Keep SSH
access enabled. If using a hostname, point its A record to the VPS, use
Cloudflare DNS-only mode, and remove any stale AAAA record.

Clone this branch, then run:

```bash
git clone --branch feature/direct-vps-egress https://github.com/celia-hk-infra/webstudio-utils.git
cd webstudio-utils
sudo ./setup_vps.sh
```

The installer asks for the public IPv4 address or hostname, certificate contact
email, and acceptance of the Let's Encrypt subscriber agreement. For explicit
arguments:

```bash
sudo ./setup_vps.sh --address YOUR_VPS_IP --email you@example.com --agree-tos
```

It installs Docker if absent, pulls digest-pinned multi-platform images,
verifies the GOST binary checksum, obtains a certificate, starts the proxy
container, and enables automatic renewal. It checks a renewal dry run,
unauthenticated proxy rejection (407), and authenticated HTTPS forwarding with
certificate verification. Proxy checks made on the VPS need it to reach its
own public address. The WebStudio setup separately tests the external path.

When setup succeeds, retrieve the connection URL in your private SSH terminal:

```bash
sudo cat /etc/webstudio-egress/client-url
```

Its format is:

```text
https://USERNAME:PASSWORD@VPS_PUBLIC_IP:443
```

This URL contains a password. Transfer it privately; do not put it in chat,
issues, Git, shell command arguments, or shared logs.

## 2. On WebStudio

Clone the same branch, then run:

```bash
./setup_tools.sh --agents codex --official --skip-vscode --direct-egress
source shell/init.sh
```

Paste the private proxy URL at the hidden prompt. Setup stores it with mode
600, checks connectivity, and installs the local GOST client. Omit
`--skip-vscode` if you also want the separate VS Code tunnel setup.

Sign in when setup offers, or afterward:

```bash
codex login --device-auth
codex
```

The container connects to your VPS on port 443 with verified TLS and proxy
authentication. Codex's TLS to OpenAI remains end to end. WebStudio does not
need direct SSH access to the VPS for this two-part workflow.

## Container layout and isolation

| Component | Behavior |
| --- | --- |
| `webstudio-egress` | GOST container; publishes host TCP 443 to container 8443 |
| `webstudio-egress-certbot` | Temporary Certbot container; publishes TCP 80 to 8080 only during issuance/renewal |
| Docker network `webstudio-egress` | Dedicated bridge network with outbound internet access |
| `gost-egress.service` | Starts/stops the proxy container; enabled at boot |
| `webstudio-certbot.timer` | Starts containerized renewal twice daily |
| `/etc/webstudio-egress/` | Private persistent deployment state, credentials, binary, and certificate storage |

Both containers have read-only root filesystems, all Linux capabilities dropped,
`no-new-privileges`, a process limit, bounded writable tmpfs directories, and
rotating Docker logs. They have neither privileged mode nor host networking,
and **neither receives the Docker socket**. They run as container root to access
root-owned private files, without Linux capabilities. This is container
isolation, not a separate VM or protection from the VPS administrator.

GOST receives only its binary, proxy configuration, and the certificate lineage's
`live` and `archive` directories, all mounted read-only. It cannot access the
Certbot account directory or write to certificate storage. Certbot receives
writable certificate storage; its working files and logs use disposable tmpfs.

GOST 3.3.3 is downloaded from its official release and SHA-256 checked. The
minimal runtime image is BusyBox 1.37.0; the certificate image is Certbot 5.4.0.
Both images are pinned by multi-platform manifest digest and support ARM64 and
amd64. No GOST or Certbot process runs natively on the host. Docker, the Python
installer/renewal supervisor, and systemd run on the host. Installing Docker
changes host networking through Docker's normal firewall management.

## Certificates, renewal, and reruns

Certbot uses standalone HTTP-01 validation, so cloud inbound port 80 must remain
allowed for future renewals. IP certificates use the short-lived profile
(about six days). The timer runs renewal twice daily; Certbot decides when the
certificate needs renewing.

The host renewal supervisor compares the certificate digest with the last
loaded certificate and restarts GOST only when needed. It records the digest
after a successful restart, so a failed restart is retried on the next run.
Certbot never controls Docker from inside its container. Renewal and setup use
the same host lock to avoid overlapping challenge listeners. Dry-run renewal
does not replace the active certificate or trigger a restart.

Credentials and certificates survive container replacement and reboot. Reruns
preserve credentials, but restart the proxy and briefly interrupt connections.
Changing an existing deployment address is refused. Existing native GOST
services and unrelated containers/networks are not automatically migrated or
replaced. There is no automatic password rotation, image upgrade, or uninstall.

Useful paths:

- `/etc/webstudio-egress/deployment.json`: reusable proxy credentials and address.
- `/etc/webstudio-egress/gost.json`: private GOST configuration.
- `/etc/webstudio-egress/client-url`: the only value to copy to WebStudio.
- `/etc/webstudio-egress/letsencrypt/`: persistent ACME account and certificate keys.
- `/etc/webstudio-egress/manager.py`: installed host renewal supervisor.
- `$WEBSTUDIO_AGENT_STATE_DIR/egress/direct-proxy.json`: WebStudio's private URL.

Private files are protected by permissions, not encrypted at rest. Anyone with
root or Docker administrative access on the VPS can access container secrets.

## Firewall behavior

Docker publishes 80/443 using its own NAT/forwarding rules. **UFW's normal INPUT
rules do not reliably filter published container ports.** Do not use `ufw status`
as evidence that a Docker service is blocked or restricted. Apply public access
rules in the cloud firewall, and use Docker-aware host filtering (such as
`DOCKER-USER` with the iptables backend) if additional restrictions are needed.

The earlier native-service installer's Oracle INPUT-chain reject check does not
apply to this Docker network path. The installer no longer treats that rule as
a definitive blocker. It does not manually delete or rewrite your existing
rules; Docker itself installs its normal networking rules. Cloud or custom
forwarding rules can still block validation and proxy access. Keep SSH and
Oracle instance-service rules intact.

See [Docker firewall behavior](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
and [Let's Encrypt IP certificate support](https://letsencrypt.org/2026/03/11/shorter-certs-certbot).

## Inspect, stop, and restart

On the VPS:

```bash
sudo systemctl status gost-egress webstudio-certbot.timer
sudo docker ps --filter name=webstudio-egress
sudo docker logs --tail 50 webstudio-egress
sudo journalctl -u webstudio-certbot --no-pager -n 50
sudo systemctl restart gost-egress
```

Stop the proxy using `sudo systemctl stop gost-egress` rather than `docker stop`:
systemd supervises the container and restarts unexpected exits. To disable the
whole deployment at boot, disable both the proxy and renewal timer. Persistent
state remains available for recovery:

```bash
sudo systemctl disable --now webstudio-certbot.timer gost-egress.service
```

If a renewal is already running, let it finish before stopping the proxy or
also stop `webstudio-certbot.service` deliberately. A future renewal run can
restart the proxy when it needs to load a new certificate.

On WebStudio:

```bash
python3 scripts/direct_egress.py check
```

## Optional SSH automation

The two-part setup above is the default recommendation. The optional
`scripts/provision_vps.py` and `setup_tools.sh --setup-vps` helpers still exist
for environments with SSH connectivity. They run the same Docker installer
remotely and retrieve the URL securely. The explicit helper accepts `--host`,
`--user`, `--port`, `--identity`, `--address`, `--email`, and `--agree-tos`.
It can use an already configured direct HTTPS proxy for SSH with
`--via-existing-proxy`. SSH host keys are verified; private keys are never
copied or forwarded. These helpers require root or passwordless sudo and are
not necessary for the two-part workflow.
