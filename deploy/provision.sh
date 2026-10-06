#!/usr/bin/env bash
# ONE-TIME server setup for this app. Idempotent — safe to re-run.
#   bash deploy/provision.sh app     user, units, code, venv, start on 127.0.0.1 (no DNS needed)
#   bash deploy/provision.sh web     nginx site + Let's Encrypt cert (needs DNS pointing at HOST)
#   bash deploy/provision.sh         both
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
SSH="ssh -i $SSH_KEY -o ConnectTimeout=15 $SSH_USER@$HOST"

render() { sed "s/__DOMAIN__/$DOMAIN/g; s/__PORT__/$PORT/g" "$1"; }
PHASE=${1:-all}

if [ "$PHASE" = app ] || [ "$PHASE" = all ]; then
echo "→ user, dirs"
$SSH "sudo bash -s" <<REMOTE
set -euo pipefail
id -u $APP >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin $APP
mkdir -p /srv/$APP /var/www/html
REMOTE

echo "→ code, venv, units"
bash deploy/deploy.sh --no-restart
$SSH "sudo systemctl daemon-reload && sudo systemctl enable --now $APP $APP-backup.timer && sleep 2 && curl -fsS http://127.0.0.1:$PORT/healthz && echo"
fi

if [ "$PHASE" = web ] || [ "$PHASE" = all ]; then
echo "→ nginx + TLS"
# 1) HTTP-only site so Let's Encrypt can reach the challenge, 2) cert, 3) full site.
render deploy/nginx.conf | awk '/^server \{/{n++} n<2' | $SSH "sudo tee /etc/nginx/sites-available/$APP >/dev/null"
$SSH "sudo bash -s" <<REMOTE
set -euo pipefail
ln -sf /etc/nginx/sites-available/$APP /etc/nginx/sites-enabled/$APP
nginx -t && systemctl reload nginx
[ -d /etc/letsencrypt/live/$DOMAIN ] || certbot certonly --webroot -w /var/www/html -d $DOMAIN --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring
REMOTE
render deploy/nginx.conf | $SSH "sudo tee /etc/nginx/sites-available/$APP >/dev/null"
$SSH "sudo bash -s" <<REMOTE
set -euo pipefail
[ -f /etc/letsencrypt/options-ssl-nginx.conf ] || sed -i '/options-ssl-nginx.conf/d' /etc/nginx/sites-available/$APP
nginx -t && systemctl reload nginx
REMOTE
curl -fsS "https://$DOMAIN/healthz" && echo
fi
echo "✓ provisioned ($PHASE) — create your login with: bash deploy/admin.sh create-user you@example.com 'Your Name'"
