# Where this app lives. Sourced by provision.sh and deploy.sh.
APP=sales-pipeline
PORT=8100                              # see "Port registry" in deploy/README.md
DOMAIN=sales.muhammadtalhabinzia.com
HOST=<server-ip>                       # server v2 public IP (becomes the EIP <elastic-ip> at FirstGlance cutover)
SSH_USER=<ssh-user>
SSH_KEY=~/.ssh/<server-key>
