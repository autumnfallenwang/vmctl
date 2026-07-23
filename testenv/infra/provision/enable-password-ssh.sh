#!/usr/bin/env bash
# Vagrant shell provisioner (runs as root inside the guest).
#
# Creates the vmctl test login and turns on SSH password authentication, so
# vmctl's real username/password auth path can be exercised. Vagrant itself only
# wires key-based access for the `vagrant` user; this adds the password path.
#
# Idempotent — safe to re-run on `vagrant provision`.
set -euo pipefail

USER_NAME="${VMCTL_SSH_USER:-vmctl}"
USER_PW="${VMCTL_SSH_PASSWORD:-changeme}"

# Create the login if it does not exist yet, then (re)set its password.
if ! id "$USER_NAME" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$USER_NAME"
fi
echo "${USER_NAME}:${USER_PW}" | chpasswd

# Rocky 9 ships PasswordAuthentication in the main config but drop-ins under
# /etc/ssh/sshd_config.d/ can override it. Force it on with a high-priority drop-in.
install -m 0644 /dev/stdin /etc/ssh/sshd_config.d/60-vmctl.conf <<'EOF'
# Managed by vmctl testenv (enable-password-ssh.sh) — password auth for testing.
PasswordAuthentication yes
EOF

systemctl restart sshd

echo "vmctl: password SSH enabled for user '${USER_NAME}'"
