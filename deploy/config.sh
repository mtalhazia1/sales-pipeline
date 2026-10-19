# Where this app lives. Sourced by provision.sh and deploy.sh.
APP=sales-pipeline
PORT=8100                              # see "Port registry" in deploy/README.md
DOMAIN=sales.muhammadtalhabinzia.com
# HOST, SSH_USER, SSH_KEY: server access, kept out of the (public) repo.
[ -f deploy/config.local.sh ] || { echo "deploy/config.local.sh missing: copy deploy/config.local.example.sh" >&2; exit 1; }
source deploy/config.local.sh
