#!/usr/bin/env bash
# Run an admin command on the server as the app user:
#   bash deploy/admin.sh create-user you@example.com "Your Name"
#   bash deploy/admin.sh reset-password you@example.com
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
args=$(printf '%q ' "$@")
ssh -i "$SSH_KEY" "$SSH_USER@$HOST" "cd /srv/$APP/server && sudo -u $APP env SP_DATA_DIR=/var/lib/$APP /srv/$APP/.venv/bin/python -m app.cli $args"
