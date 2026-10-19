# Deploying — and the convention for every project on the shared EC2

The server (Ubuntu 24.04) hosts several independent projects. Each one follows
the same pattern so they cannot interfere with each other, and so the next project is a copy-paste:

| Concern | Per project | Here |
|---|---|---|
| Linux user | own system user, no login, no home | `sales-pipeline` |
| Code | `/srv/<app>/` owned by root — the app can't modify its own code | `/srv/sales-pipeline` |
| Data | `/var/lib/<app>/` (systemd `StateDirectory`, mode 0700, `UMask=0077`) — the only writable path. **Every** unit that names the StateDirectory must set the same mode: systemd re-applies it on each start (a backup unit without it reset the dir to 0755) | SQLite at `/var/lib/sales-pipeline/sales.db` |
| Process | own systemd unit: `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `NoNewPrivileges`, `MemoryMax` | `sales-pipeline.service` |
| Network | binds `127.0.0.1:<port>` only; public traffic via its own nginx site file + its own LE cert | port 8100, `sales.<domain>` |
| Secrets | none shared; each app keeps its own | none needed (no external APIs) |
| Backups | own timer; EBS snapshots (volume tag `Backup=prod`) carry the files off-box | daily `sqlite` snapshot, 14 kept |

What is shared on purpose: nginx (one config file per project), certbot, the OS. Nothing else — no shared
database server, no shared users, no shared secrets.

## Port registry

| Port | Project |
|---|---|
| 3000 / 3001 | FirstGlance web (blue-green) |
| 5000 | FirstGlance API (gunicorn) |
| 8100 | Sales Pipeline |
| — | personal-site (static, nginx only) — `~/Code/personal-site` |

## First time (once)

0. `cp deploy/config.local.example.sh deploy/config.local.sh` and fill in the server's host, SSH user and key
   (git-ignored: this repo is public, so server access details never go in it).
1. DNS: `A` record for `DOMAIN` → the server IP (muhammadtalhabinzia.com is at Namecheap).
2. Ports 80 + 443 must be reachable from the internet for Let's Encrypt and for Claude's connector
   (the server's security group); keep SSH limited to your own IPs.
3. `bash deploy/provision.sh app` — user, units, code, start (no DNS needed); then
   `bash deploy/provision.sh web` — nginx site + TLS cert (needs the DNS record live).
4. `bash deploy/admin.sh create-user you@example.com "Your Name"` — prints a password; change it in Settings.

## Every deploy

`bash deploy/deploy.sh` — builds the UI locally, rsyncs code, re-installs the systemd units and the nginx
site from the repo (a site file that fails `nginx -t` is rolled back — nginx is shared), installs Python
deps, restarts (Alembic migrations run on start), health-checks. The server never drifts from the repo. Config: app, domain and port in `deploy/config.sh`; host, SSH user and key in the git-ignored
`deploy/config.local.sh`.

## Operating

```bash
ssh -i <key> <user>@<host>                     # from deploy/config.local.sh
sudo systemctl status sales-pipeline          # state
sudo journalctl -u sales-pipeline -n 100      # logs
ls /var/lib/sales-pipeline/backups            # snapshots (restore: stop service, copy over sales.db, start)
```

If the server's public IP changes, re-point the DNS records and update `HOST` in `deploy/config.local.sh`
(and in the other projects on the box).
