# Deploying — and the convention for every project on the shared EC2

The server (`<instance-id>`, Ubuntu 24.04) hosts several independent projects. Each one follows
the same pattern so they cannot interfere with each other, and so the next project is a copy-paste:

| Concern | Per project | Here |
|---|---|---|
| Linux user | own system user, no login, no home | `sales-pipeline` |
| Code | `/srv/<app>/` owned by root — the app can't modify its own code | `/srv/sales-pipeline` |
| Data | `/var/lib/<app>/` (systemd `StateDirectory`, mode 0700) — the only writable path | SQLite at `/var/lib/sales-pipeline/sales.db` |
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

## First time (once)

1. DNS: `A` record for `DOMAIN` → the server IP (Route 53, profile `fg-new`).
2. Ports 80 + 443 must be reachable from the internet for Let's Encrypt and for Claude's connector
   (security group `<security-group>`).
3. `bash deploy/provision.sh` — creates the user, units, nginx site, TLS cert, deploys, starts.
4. `bash deploy/admin.sh create-user you@example.com "Your Name"` — prints a password; change it in Settings.

## Every deploy

`bash deploy/deploy.sh` — builds the UI locally, rsyncs code, installs Python deps, restarts (Alembic
migrations run on start), health-checks. Config (host, key, domain, port) lives in `deploy/config.sh`.

## Operating

```bash
ssh -i ~/.ssh/<server-key> <ssh-user>@<host>
sudo systemctl status sales-pipeline          # state
sudo journalctl -u sales-pipeline -n 100      # logs
ls /var/lib/sales-pipeline/backups            # snapshots (restore: stop service, copy over sales.db, start)
```

When FirstGlance cuts over to this box (the Elastic IP moves here), update the `A` record and `HOST` in `config.sh`.
