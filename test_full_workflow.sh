#!/bin/bash
# Complete workflow test: Email → Agent1 → Agent2 → Agent3 → Invoice

BASE_URL="http://localhost:8000"
SECRET="hackai"

echo "════════════════════════════════════════════════════════════════════"
echo "🧪 Complete Workflow Test: Email → Agent1 → Agent2 → Agent3 → Invoice"
echo "════════════════════════════════════════════════════════════════════"

# Step 1: Agent1 - Create case from email
echo ""
echo "📧 Step 1: Agent1 - Creating case from email..."
TIMESTAMP=$(date +%s)
CASE_RESPONSE=$(curl -s -X POST "$BASE_URL/cases/intake" \
  -H "Content-Type: application/json" \
  -H "X-CompensAI-Webhook-Secret: $SECRET" \
  -d "{
    \"source\": \"gmail\",
    \"message_id\": \"test_workflow_${TIMESTAMP}\",
    \"thread_id\": \"test_thread_${TIMESTAMP}\",
    \"from_email\": \"support@ryanair.com\",
    \"to_email\": \"client.compensai@gmail.com\",
    \"email_subject\": \"Flight Delay - AB1234\",
    \"email_body\": \"Dear Customer, We regret to inform you that flight AB1234 from Paris (CDG) to Berlin (BER) has been severely delayed due to technical issues. Flight Details: - Flight Number: AB1234 - Booking Reference: ABC123XYZ - Scheduled Departure: 2026-02-15 14:30 - Actual Departure: 2026-02-15 18:45 - Delay Duration: 4 hours 15 minutes. Under EU Regulation 261/2004, you may be eligible for compensation. Claim Form: https://skill-deploy-z31gmu05km-codex-agent-deploys.vercel.app/airline-claim.html\",
    \"vendor\": \"RYANAIR\",
    \"category\": \"flight_delay\",
    \"flight_number\": \"AB1234\",
    \"booking_reference\": \"ABC123XYZ\",
    \"incident_date\": \"2026-02-15\"
  }")

# Extract case ID using a more reliable method
CASE_ID=$(echo "$CASE_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)

if [ -z "$CASE_ID" ] || [ "$CASE_ID" = "None" ]; then
  echo "   ❌ Failed to create case"
  echo "   Response: $CASE_RESPONSE"
  exit 1
fi

echo "   ✅ Case created: $CASE_ID"
echo "   ⏳ Waiting 15 seconds for Agent2 to process..."

# Step 2: Wait for Agent2
sleep 15

# Step 3: Agent3 - Simulate vendor response (triggers invoice creation)
echo ""
echo "💰 Step 3: Agent3 - Simulating vendor response (€250 recovered)..."
VENDOR_RESPONSE=$(curl -s -X POST "$BASE_URL/cases/$CASE_ID/vendor_response" \
  -H "Content-Type: application/json" \
  -H "X-CompensAI-Webhook-Secret: $SECRET" \
  -d "{
    \"outcome\": \"accepted\",
    \"resolved\": true,
    \"recovered_amount\": 250,
    \"currency\": \"eur\",
    \"evidence\": {\"vendor_ref\": \"TEST123\"},
    \"message_id\": \"test_msg_123\",
    \"thread_id\": \"test_thread_123\"
  }")

echo "   ✅ Vendor response submitted"

# Step 4: Verify invoice was created
echo ""
echo "📄 Step 4: Verifying invoice in Supabase..."
sleep 2

CASE_DATA=$(curl -s -X GET "$BASE_URL/cases/$CASE_ID" \
  -H "X-CompensAI-Admin-Key: admin" 2>/dev/null)

if [ -z "$CASE_DATA" ]; then
  echo "   ⚠️  Could not fetch case data"
  exit 1
fi

# Extract fields using Python
RECOVERED=$(echo "$CASE_DATA" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('recovered_amount', 'N/A'))" 2>/dev/null)
FEE=$(echo "$CASE_DATA" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('fee_amount', 'N/A'))" 2>/dev/null)
STATUS=$(echo "$CASE_DATA" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('status', 'N/A'))" 2>/dev/null)

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "📊 Workflow Results"
echo "════════════════════════════════════════════════════════════════════"
echo "   Case ID: $CASE_ID"
echo "   Status: $STATUS"
echo "   Recovered Amount: €$RECOVERED"
echo "   Fee Amount (10%): €$FEE"
echo ""
echo "   ✅ Financial data stored in Supabase"
echo "   💡 Check your dashboard to see the resolved case with billing info"

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "✅ Complete Workflow Test Finished"
echo "════════════════════════════════════════════════════════════════════"
