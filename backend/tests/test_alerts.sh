#!/usr/bin/env bash
PASS=0; FAIL=0
BASE="http://localhost:8000"
COOKIE_JAR=$(mktemp)

ok()  { echo "  PASS  $1"; PASS=$((PASS+1)); }
fail(){ echo "  FAIL  $1 -- $2"; FAIL=$((FAIL+1)); }

post()  { curl -s -X POST   -H "Content-Type: application/json" -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$@"; }
get()   { curl -s -X GET    -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$@"; }
patch() { curl -s -X PATCH  -H "Content-Type: application/json" -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$@"; }
del()   { curl -s -X DELETE -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$@"; }
py()    { python3 -c "$1" 2>/dev/null; }

# 1. Register
EMAIL="alerttest_$(date +%s)@example.com"
REG=$(post "$BASE/api/auth/register" -d "{\"email\":\"$EMAIL\",\"password\":\"password123\"}")
[[ "$REG" == *"$EMAIL"* ]] && ok "register" || fail "register" "$REG"

# 2. GET /api/alerts -- empty
R=$(get "$BASE/api/alerts")
ALERTS=$(py "import sys,json; d=json.loads('''$R'''); print(len(d['alerts']))")
UNREAD=$(py "import sys,json; d=json.loads('''$R'''); print(d['unread_count'])")
[[ "$ALERTS" == "0" && "$UNREAD" == "0" ]] && ok "GET /api/alerts (empty)" || fail "GET /api/alerts empty" "$R"

# 3. Add subscription due in 3 days
FUTURE=$(python3 -c "from datetime import date,timedelta; print((date.today()+timedelta(days=3)).isoformat())")
SUB=$(post "$BASE/api/subscriptions/manual" -d "{\"merchant\":\"TestFlix\",\"amount\":15.99,\"frequency\":\"monthly\",\"next_expected\":\"$FUTURE\"}")
SUB_ID=$(echo "$SUB" | python3 -c "import sys,json; print(json.load(sys.stdin)['subscription']['id'])")
[[ -n "$SUB_ID" ]] && ok "add manual subscription (due in 3 days)" || fail "add subscription" "$SUB"

# 4. Generate alerts
GEN=$(post "$BASE/api/alerts/generate")
COUNT=$(echo "$GEN" | python3 -c "import sys,json,re; m=re.search(r'[0-9]+',json.load(sys.stdin)['message']); print(m.group() if m else -1)")
[[ "$COUNT" == "1" ]] && ok "POST /api/alerts/generate (1 created)" || fail "generate" "$GEN"

# 5. GET alerts -- 1 unread
R=$(get "$BASE/api/alerts")
UNREAD=$(echo "$R" | python3 -c "import sys,json; print(json.load(sys.stdin)['unread_count'])")
ALERT_ID=$(echo "$R" | python3 -c "import sys,json; a=json.load(sys.stdin)['alerts']; print(a[0]['id'] if a else '')")
[[ "$UNREAD" == "1" && -n "$ALERT_ID" ]] && ok "GET /api/alerts (1 unread)" || fail "1 unread" "$R"

# 6. Alert message contains merchant
MSG=$(get "$BASE/api/alerts" | python3 -c "import sys,json; print(json.load(sys.stdin)['alerts'][0]['message'])")
[[ "$MSG" == *"TestFlix"* ]] && ok "alert message mentions merchant" || fail "message content" "$MSG"

# 7. Idempotent -- generate again yields 0
GEN2=$(post "$BASE/api/alerts/generate")
COUNT2=$(echo "$GEN2" | python3 -c "import sys,json,re; m=re.search(r'[0-9]+',json.load(sys.stdin)['message']); print(m.group() if m else -1)")
[[ "$COUNT2" == "0" ]] && ok "generate again is idempotent (0 duplicates)" || fail "idempotency" "$GEN2"

# 8. Mark read
READ_R=$(patch "$BASE/api/alerts/$ALERT_ID/read")
IS_READ=$(echo "$READ_R" | python3 -c "import sys,json; print(json.load(sys.stdin)['is_read'])")
[[ "$IS_READ" == "True" ]] && ok "PATCH /api/alerts/{id}/read" || fail "mark read" "$READ_R"

# 9. Unread drops to 0
UNREAD2=$(get "$BASE/api/alerts" | python3 -c "import sys,json; print(json.load(sys.stdin)['unread_count'])")
[[ "$UNREAD2" == "0" ]] && ok "unread_count drops to 0" || fail "unread count" "$UNREAD2"

# 10. 404 on unknown alert
FAKE=$(python3 -c "import uuid; print(uuid.uuid4())")
STATUS=$(patch "$BASE/api/alerts/$FAKE/read" -o /dev/null -w "%{http_code}")
[[ "$STATUS" == "404" ]] && ok "PATCH unknown alert -> 404" || fail "unknown 404" "$STATUS"

# 11. Delete alert
DEL_R=$(del "$BASE/api/alerts/$ALERT_ID")
[[ "$DEL_R" == *"deleted"* ]] && ok "DELETE /api/alerts/{id}" || fail "delete" "$DEL_R"

# 12. Gone after delete
REMAINING=$(get "$BASE/api/alerts" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['alerts']))")
[[ "$REMAINING" == "0" ]] && ok "alert gone after delete" || fail "still present" "$REMAINING"

# 13. 404 on already-deleted
STATUS2=$(del "$BASE/api/alerts/$ALERT_ID" -o /dev/null -w "%{http_code}")
[[ "$STATUS2" == "404" ]] && ok "DELETE deleted alert -> 404" || fail "delete twice" "$STATUS2"

# 14. PATCH /api/auth/me -- alert prefs
ME=$(patch "$BASE/api/auth/me" -d '{"alert_email": true, "alert_sms": false}')
AE=$(echo "$ME" | python3 -c "import sys,json; print(json.load(sys.stdin)['alert_email'])")
AS=$(echo "$ME" | python3 -c "import sys,json; print(json.load(sys.stdin)['alert_sms'])")
[[ "$AE" == "True" && "$AS" == "False" ]] && ok "PATCH /api/auth/me (alert prefs)" || fail "alert prefs" "$ME"

# 15. GET /api/auth/me reflects saved prefs
AE2=$(get "$BASE/api/auth/me" | python3 -c "import sys,json; print(json.load(sys.stdin)['alert_email'])")
[[ "$AE2" == "True" ]] && ok "GET /api/auth/me reflects saved prefs" || fail "prefs not persisted" "$AE2"

# 16. "today" in message when due today
TODAY=$(python3 -c "from datetime import date; print(date.today().isoformat())")
post "$BASE/api/subscriptions/manual" -d "{\"merchant\":\"TodaySub\",\"amount\":9.99,\"frequency\":\"monthly\",\"next_expected\":\"$TODAY\"}" > /dev/null
post "$BASE/api/alerts/generate" > /dev/null
MSG2=$(get "$BASE/api/alerts" | python3 -c "import sys,json; alerts=json.load(sys.stdin)['alerts']; print(next((a['message'] for a in alerts if 'TodaySub' in a['message']),'NOT_FOUND'))")
[[ "$MSG2" == *"today"* ]] && ok "due today -> 'today' in message" || fail "today message" "$MSG2"

# 17. "tomorrow" in message when due tomorrow
TOMORROW=$(python3 -c "from datetime import date,timedelta; print((date.today()+timedelta(days=1)).isoformat())")
post "$BASE/api/subscriptions/manual" -d "{\"merchant\":\"TomorrowSub\",\"amount\":4.99,\"frequency\":\"monthly\",\"next_expected\":\"$TOMORROW\"}" > /dev/null
post "$BASE/api/alerts/generate" > /dev/null
MSG3=$(get "$BASE/api/alerts" | python3 -c "import sys,json; alerts=json.load(sys.stdin)['alerts']; print(next((a['message'] for a in alerts if 'TomorrowSub' in a['message']),'NOT_FOUND'))")
[[ "$MSG3" == *"tomorrow"* ]] && ok "due tomorrow -> 'tomorrow' in message" || fail "tomorrow message" "$MSG3"

# 18. Logout
LO=$(post "$BASE/api/auth/logout")
[[ "$LO" == *"Logged out"* ]] && ok "logout" || fail "logout" "$LO"

rm -f "$COOKIE_JAR"

echo ""
echo "--------------------------------"
echo "  PASS: $PASS   FAIL: $FAIL"
echo "--------------------------------"
[[ $FAIL -eq 0 ]] && echo "  All $PASS tests passed." || echo "  $FAIL test(s) failed."
echo "--------------------------------"
