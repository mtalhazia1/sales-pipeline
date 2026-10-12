#!/usr/bin/env bash
# Deploy the current working tree: build the UI locally, sync code, install deps, restart.
#   bash deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
SSH="ssh -i $SSH_KEY -o ConnectTimeout=15 $SSH_USER@$HOST"
RSYNC=(rsync -rlptz --delete --rsync-path="sudo rsync" -e "ssh -i $SSH_KEY")

echo "→ building web UI"
(cd web && npm ci --silent && npm run build >/dev/null)

echo "→ syncing to $HOST"
$SSH "sudo mkdir -p /srv/$APP/server /srv/$APP/web/dist"
"${RSYNC[@]}" --exclude __pycache__ --exclude 'scripts/seed_demo.py' server/ "$SSH_USER@$HOST:/srv/$APP/server/"
"${RSYNC[@]}" web/dist/ "$SSH_USER@$HOST:/srv/$APP/web/dist/"
# Code is root-owned and world-readable: the app user can read it but never modify it.
$SSH "sudo chown -R root:root /srv/$APP/server /srv/$APP/web && sudo chmod -R u=rwX,go=rX /srv/$APP/server /srv/$APP/web"

echo "→ systemd units (re-installed every deploy so the server always matches the repo)"
render() { sed "s/__DOMAIN__/$DOMAIN/g; s/__PORT__/$PORT/g" "$1"; }
for unit in $APP.service $APP-backup.service $APP-backup.timer; do
  render "deploy/$unit" | $SSH "sudo tee /etc/systemd/system/$unit >/dev/null"
done
# Data is private to the app user (UMask=0077 covers new files; this heals files made before it).
$SSH "sudo systemctl daemon-reload && { sudo chmod -R go= /var/lib/$APP 2>/dev/null || true; }"

# nginx is shared with the other projects: a site file that fails `nginx -t` is rolled back, never left in place.
if $SSH "sudo test -d /etc/letsencrypt/live/$DOMAIN"; then  # (first run: provision.sh web gets the cert first)
  echo "→ nginx site"
  # Staged inside root-owned sites-available (never a world-writable /tmp path another user could symlink).
  render deploy/nginx.conf | $SSH "sudo tee /etc/nginx/sites-available/.$APP.new >/dev/null"
  $SSH "sudo bash -s" <<REMOTE
set -euo pipefail
site=/etc/nginx/sites-available/$APP
cp \$site \$site.prev 2>/dev/null || true
mv /etc/nginx/sites-available/.$APP.new \$site && chmod 644 \$site
if nginx -t 2>/dev/null; then systemctl reload nginx; rm -f \$site.prev
else echo "nginx -t failed — keeping the previous site file" >&2; mv \$site.prev \$site; exit 1; fi
REMOTE
fi

echo "→ installing dependencies"
$SSH "sudo bash -s" <<REMOTE
set -euo pipefail
[ -x /srv/$APP/.venv/bin/python ] || python3.12 -m venv /srv/$APP/.venv
/srv/$APP/.venv/bin/pip install -q --disable-pip-version-check -r /srv/$APP/server/requirements.txt
REMOTE

if [ "${1:-}" != "--no-restart" ]; then
  echo "→ restarting (migrations run on start)"
  # Startup takes a few seconds (migrations, imports): poll instead of a fixed sleep.
  $SSH "sudo systemctl restart $APP && for i in \$(seq 20); do curl -fsS http://127.0.0.1:$PORT/healthz 2>/dev/null && break; sleep 1; done; echo && systemctl is-active $APP"
  curl -fsS -o /dev/null -w "public https://$DOMAIN/healthz → %{http_code}\n" "https://$DOMAIN/healthz" || echo "(public check failed — DNS/firewall?)"
fi
