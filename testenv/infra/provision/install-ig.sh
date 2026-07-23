#!/usr/bin/env bash
# Vagrant shell provisioner (runs as root inside the guest).
#
# Installs JDK 17 + PingGateway IG, lays down the IG instance config (no AM — a
# plain reverse-proxy route to the local stub, with JSON audit logging), and runs
# both under systemd. Idempotent — safe to re-run via `vagrant provision`.
set -euo pipefail

IG_ZIP="/tmp/pinggateway.zip"
BUNDLE="/tmp/vmctl-ig"          # uploaded ig/ dir (config, stub-app.py, systemd)
IG_HOME_PARENT="/opt"
IG_INSTANCE_DIR="/opt/ig-instance"
SVC_USER="${VMCTL_SSH_USER:-vmctl}"

echo "== install JDK 17 + unzip =="
dnf install -y --setopt=install_weak_deps=False java-17-openjdk-headless unzip >/dev/null

JAVA_BIN="$(command -v java)"
JAVA_HOME="$(dirname "$(dirname "$(readlink -f "$JAVA_BIN")")")"
echo "   JAVA_HOME=$JAVA_HOME"

echo "== unpack PingGateway =="
[ -f "$IG_ZIP" ] || { echo "ERROR: $IG_ZIP not found (drop the binary in testenv/infra/artifacts/)"; exit 1; }
unzip -q -o "$IG_ZIP" -d "$IG_HOME_PARENT"
IG_HOME="$(find "$IG_HOME_PARENT" -maxdepth 1 -type d \( -iname 'identity-gateway-*' -o -iname 'pinggateway-*' \) | sort | tail -1)"
[ -n "$IG_HOME" ] && [ -x "$IG_HOME/bin/start.sh" ] || { echo "ERROR: IG start.sh not found under $IG_HOME_PARENT"; ls -la "$IG_HOME_PARENT"; exit 1; }
echo "   IG_HOME=$IG_HOME"

echo "== lay down instance config =="
mkdir -p "$IG_INSTANCE_DIR/config/routes" "$IG_INSTANCE_DIR/logs/audit"
cp -f "$BUNDLE/config/admin.json"  "$IG_INSTANCE_DIR/config/admin.json"
cp -f "$BUNDLE/config/logback.xml" "$IG_INSTANCE_DIR/config/logback.xml"
# No config.json: IG's default router serves config/routes/ (audit is per-route).
# Remove any stale one from an earlier provision so it can't override the router.
if [ -f "$BUNDLE/config/config.json" ]; then
  cp -f "$BUNDLE/config/config.json" "$IG_INSTANCE_DIR/config/config.json"
else
  rm -f "$IG_INSTANCE_DIR/config/config.json"
fi
cp -f "$BUNDLE/config/routes/"*.json "$IG_INSTANCE_DIR/config/routes/"

echo "== stub upstream =="
mkdir -p /opt/stub
cp -f "$BUNDLE/stub-app.py" /opt/stub/stub-app.py

echo "== ownership =="
chown -R "$SVC_USER:$SVC_USER" "$IG_INSTANCE_DIR" /opt/stub "$IG_HOME"

echo "== systemd env + units =="
cat >/etc/sysconfig/pinggateway <<EOF
JAVA_HOME=$JAVA_HOME
IG_INSTANCE_DIR=$IG_INSTANCE_DIR
IG_START=$IG_HOME/bin/start.sh
JAVA_OPTS=-Xmx768m
EOF
cp -f "$BUNDLE/systemd/stub-app.service"    /etc/systemd/system/stub-app.service
cp -f "$BUNDLE/systemd/pinggateway.service" /etc/systemd/system/pinggateway.service
systemctl daemon-reload
systemctl enable --now stub-app.service
systemctl restart pinggateway.service

# Open the IG port so the host-side test engine can reach it. The stub (:8081)
# stays loopback-only — only IG reaches it.
if systemctl is-active --quiet firewalld; then
  echo "== open firewalld 9080/tcp =="
  firewall-cmd --add-port=9080/tcp --permanent >/dev/null
  firewall-cmd --reload >/dev/null
fi

echo "== wait for IG :9080 =="
for _ in $(seq 40); do
  code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9080/ 2>/dev/null || echo 000)"
  [ "$code" = "200" ] && { echo "   IG is serving (HTTP $code)"; exit 0; }
  sleep 3
done
echo "WARNING: IG did not return 200 on :9080 in time — check 'journalctl -u pinggateway'"
exit 1
