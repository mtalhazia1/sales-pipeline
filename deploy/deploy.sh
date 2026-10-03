#!/usr/bin/env bash
# Deploy the current working tree: build the UI locally, sync code, install deps, restart.
#   bash deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
SSH="ssh -i $SSH_KEY -o ConnectTimeout=15 $SSH_USER@$HOST"
RSYNC=(rsync -az --delete --rsync-path="sudo rsync" --chown=root:root -e "ssh -i $SSH_KEY")

echo "→ building web UI"
(cd web && npm ci --silent && npm run build >/dev/null)

echo "→ syncing to $HOST"
$SSH "sudo mkdir -p /srv/$APP/server /srv/$APP/web/dist"
"${RSYNC[@]}" --exclude __pycache__ --exclude 'scripts/seed_demo.py' server/ "$SSH_USER@$HOST:/srv/$APP/server/"
"${RSYNC[@]}" web/dist/ "$SSH_USER@$HOST:/srv/$APP/web/dist/"

echo "→ installing dependencies"
$SSH "sudo bash -s" <<REMOTE
set -euo pipefail
[ -x /srv/$APP/.venv/bin/python ] || python3.12 -m venv /srv/$APP/.venv
/srv/$APP/.venv/bin/pip install -q --disable-pip-version-check -r /srv/$APP/server/requirements.txt
REMOTE

if [ "${1:-}" != "--no-restart" ]; then
  echo "→ restarting (migrations run on start)"
  $SSH "sudo systemctl restart $APP && sleep 2 && curl -fsS http://127.0.0.1:$PORT/healthz && echo && systemctl is-active $APP"
  curl -fsS -o /dev/null -w "public https://$DOMAIN/healthz → %{http_code}\n" "https://$DOMAIN/healthz" || echo "(public check failed — DNS/firewall?)"
fi
