#!/usr/bin/env bash
# am-drive.sh — trigger every AM + DS log type on an AM-site host, to exercise vmctl
# collection. Runs ON an AM host (curls the local AM). Docs-verified against PingAM /
# PingDS 8.1 (see docs/milestones/10-am-support.md for the source catalogue).
#
#   usage: am-drive.sh <am-fqdn> <amadmin-password> [count]
#
# Log types triggered:
#   authentication.audit.json  <- successful + failed authentication (AM-TREE-LOGIN-*)
#   activity.audit.json        <- session create/validate/logout (AM-SESSION-*)
#   access.audit.json          <- every REST call (AM-ACCESS_ATTEMPT / -OUTCOME)
#   config.audit.json          <- create a realm (AM-CONFIG-CHANGE)
#   var/debug/*                <- raise logback level (live via Logback.jsp), then generate
#   DS ldap-access.audit.json  <- every LDAP op AM makes (DJ-LDAP) — automatic
#   catalina.out               <- AM logback runtime — automatic
set -u
AM="${1:?am fqdn, e.g. am1.vmctl.local}"; PW="${2:?amadmin password}"; N="${3:-15}"
B="http://${AM}:8080/am"
AV='Accept-API-Version: resource=2.0, protocol=1.0'
tokid() { python3 -c 'import json,sys;print(json.load(sys.stdin).get("tokenId",""))' 2>/dev/null; }
authn() { curl -s -X POST "$B/json/realms/root/authenticate" -H 'Content-Type: application/json' \
  -H "X-OpenAM-Username: $1" -H "X-OpenAM-Password: $2" -H "$AV"; }

echo "== 1. successful auth x$N  -> authentication + activity(session) + access =="
for i in $(seq 1 "$N"); do authn amadmin "$PW" -o /dev/null >/dev/null; done
TOK=$(authn amadmin "$PW" | tokid)

echo "== 2. failed auth x3      -> authentication (result=FAILED) =="
for i in 1 2 3; do authn nobody wrong-password -o /dev/null >/dev/null; done

echo "== 3. session validate + logout -> activity(AM-SESSION-DESTROYED/LOGGED_OUT) =="
curl -s -o /dev/null -X POST "$B/json/realms/root/sessions?_action=validate" \
  -H "iPlanetDirectoryPro: $TOK" -H 'Accept-API-Version: resource=3.0, protocol=1.0' \
  -H 'Content-Type: application/json' -d "{\"tokenId\":\"$TOK\"}"
curl -s -o /dev/null -X POST "$B/json/realms/root/sessions/?_action=logout" \
  -H "iPlanetDirectoryPro: $TOK" -H 'Accept-API-Version: resource=3.1, protocol=1.0' \
  -H 'Content-type: application/json'

echo "== 4. config change: create realm -> config(AM-CONFIG-CHANGE) =="
ADM=$(authn amadmin "$PW" | tokid)
RN="drive-$(date +%s)"
curl -s -o /dev/null -X POST "$B/json/global-config/realms" -H "iPlanetDirectoryPro: $ADM" \
  -H 'Accept-API-Version: resource=1.0' -H 'Content-Type: application/json' \
  -d "{\"name\":\"${RN}\",\"active\":true,\"parentPath\":\"/\",\"aliases\":[]}"

echo "== 5. policy evaluate -> access =="
curl -s -o /dev/null -X POST "$B/json/realms/root/policies?_action=evaluate" \
  -H "iPlanetDirectoryPro: $ADM" -H 'Content-Type: application/json' -H "$AV" \
  -d '{"resources":["https://www.example.com/index.html"],"application":"iPlanetAMWebAgentService"}'

echo "== 6. enable AM debug (logback, live) then generate, then revert =="
set_level() {  # <logger> <level>  — CSRF-token protected form at /am/Logback.jsp
  local ft
  ft=$(curl -s -b "iPlanetDirectoryPro=${ADM}" "$B/Logback.jsp" \
        | grep -oE 'name="formToken" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')
  curl -s -o /dev/null -b "iPlanetDirectoryPro=${ADM}" -X POST "$B/Logback.jsp" \
    --data-urlencode "logger=$1" --data-urlencode "loggerLevel=$2" --data-urlencode "formToken=${ft}"
}
for L in Authentication Session OAuth2Provider Policy IdRepo CoreSystem; do set_level "$L" Debug; done
for i in 1 2 3 4 5; do authn amadmin "$PW" -o /dev/null >/dev/null; done   # generate debug output
curl -s -o /dev/null -X POST "$B/json/realms/root/policies?_action=evaluate" \
  -H "iPlanetDirectoryPro: $ADM" -H 'Content-Type: application/json' -H "$AV" \
  -d '{"resources":["https://www.example.com/x"],"application":"iPlanetAMWebAgentService"}'
sleep 2
for L in Authentication Session OAuth2Provider Policy IdRepo CoreSystem; do set_level "$L" Error; done  # revert
echo "== done: driven $((N+3)) auths, 1 realm, 2 policy evals, session ops, debug pulse =="
