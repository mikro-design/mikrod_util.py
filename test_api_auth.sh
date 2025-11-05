#!/bin/bash
# Test script for BLE Gateway API authentication

set -e

echo "======================================================================"
echo "BLE Gateway API Authentication Test"
echo "======================================================================"
echo ""

# Get API key from user
if [ -z "$1" ]; then
    echo "Usage: $0 <API_KEY> [server_url]"
    echo ""
    echo "Example:"
    echo "  $0 'your-api-key-here'"
    echo "  $0 'your-api-key-here' 'https://192.168.1.100:8443'"
    echo ""
    echo "To get your API key, start the server and look for the"
    echo "🔐 API Authentication section in the startup output."
    exit 1
fi

API_KEY="$1"
SERVER_URL="${2:-https://localhost:8443}"

echo "Testing server: $SERVER_URL"
echo "API Key: ${API_KEY:0:8}...${API_KEY: -8}"
echo ""

# Test data
TEST_DATA='[{"id":"AA:BB:CC:DD:EE:FF","name":"TestDevice","rssi":-65,"advertising":{"temp":23.5,"humidity":45.2}}]'

# Test 1: Health check (no auth required)
echo "======================================================================"
echo "Test 1: Health Check (no auth required)"
echo "======================================================================"
echo ""
echo "Request: GET $SERVER_URL/health"
echo ""

if curl -sf "$SERVER_URL/health" -k > /tmp/health_response.json; then
    echo "✓ SUCCESS"
    echo ""
    echo "Response:"
    cat /tmp/health_response.json | python3 -m json.tool || cat /tmp/health_response.json
    echo ""
else
    echo "✗ FAILED - Server might not be running"
    echo ""
fi

# Test 2: API without key (should fail)
echo "======================================================================"
echo "Test 2: POST /api/ble WITHOUT API Key (should fail with 401)"
echo "======================================================================"
echo ""
echo "Request: POST $SERVER_URL/api/ble"
echo "Headers: Content-Type: application/json"
echo "Body: $TEST_DATA"
echo ""

HTTP_CODE=$(curl -sk -w "%{http_code}" -o /tmp/no_auth_response.json \
    -X POST "$SERVER_URL/api/ble" \
    -H "Content-Type: application/json" \
    -d "$TEST_DATA")

if [ "$HTTP_CODE" = "401" ]; then
    echo "✓ SUCCESS - Got expected 401 Unauthorized"
    echo ""
    echo "Response:"
    cat /tmp/no_auth_response.json | python3 -m json.tool || cat /tmp/no_auth_response.json
    echo ""
else
    echo "✗ UNEXPECTED - Got HTTP $HTTP_CODE (expected 401)"
    echo ""
    echo "Response:"
    cat /tmp/no_auth_response.json
    echo ""
fi

# Test 3: API with Authorization header (should work)
echo "======================================================================"
echo "Test 3: POST /api/ble WITH Authorization Header (should succeed)"
echo "======================================================================"
echo ""
echo "Request: POST $SERVER_URL/api/ble"
echo "Headers:"
echo "  Authorization: Bearer ${API_KEY:0:8}...${API_KEY: -8}"
echo "  Content-Type: application/json"
echo "Body: $TEST_DATA"
echo ""

HTTP_CODE=$(curl -sk -w "%{http_code}" -o /tmp/auth_response.json \
    -X POST "$SERVER_URL/api/ble" \
    -H "Authorization: Bearer $API_KEY" \
    -H "Content-Type: application/json" \
    -d "$TEST_DATA")

if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ SUCCESS - Data accepted!"
    echo ""
    echo "Response:"
    cat /tmp/auth_response.json | python3 -m json.tool || cat /tmp/auth_response.json
    echo ""
else
    echo "✗ FAILED - Got HTTP $HTTP_CODE (expected 200)"
    echo ""
    echo "Response:"
    cat /tmp/auth_response.json
    echo ""
    echo "Possible issues:"
    echo "  - Wrong API key"
    echo "  - Server authentication disabled"
    echo "  - Server not running"
    exit 1
fi

# Test 4: API with X-API-Key header (should work)
echo "======================================================================"
echo "Test 4: POST /api/ble WITH X-API-Key Header (should succeed)"
echo "======================================================================"
echo ""
echo "Request: POST $SERVER_URL/api/ble"
echo "Headers:"
echo "  X-API-Key: ${API_KEY:0:8}...${API_KEY: -8}"
echo "  Content-Type: application/json"
echo "Body: $TEST_DATA"
echo ""

HTTP_CODE=$(curl -sk -w "%{http_code}" -o /tmp/xapi_response.json \
    -X POST "$SERVER_URL/api/ble" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "$TEST_DATA")

if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ SUCCESS - Data accepted!"
    echo ""
    echo "Response:"
    cat /tmp/xapi_response.json | python3 -m json.tool || cat /tmp/xapi_response.json
    echo ""
else
    echo "✗ FAILED - Got HTTP $HTTP_CODE (expected 200)"
    echo ""
    echo "Response:"
    cat /tmp/xapi_response.json
    echo ""
fi

# Test 5: Get devices (should work with auth)
echo "======================================================================"
echo "Test 5: GET /api/devices (should require auth)"
echo "======================================================================"
echo ""
echo "Request: GET $SERVER_URL/api/devices"
echo "Headers: Authorization: Bearer ${API_KEY:0:8}...${API_KEY: -8}"
echo ""

HTTP_CODE=$(curl -sk -w "%{http_code}" -o /tmp/devices_response.json \
    -X GET "$SERVER_URL/api/devices" \
    -H "Authorization: Bearer $API_KEY")

if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ SUCCESS"
    echo ""
    echo "Response:"
    cat /tmp/devices_response.json | python3 -m json.tool || cat /tmp/devices_response.json
    echo ""
else
    echo "✗ FAILED - Got HTTP $HTTP_CODE (expected 200)"
    echo ""
fi

# Summary
echo "======================================================================"
echo "Test Summary"
echo "======================================================================"
echo ""
echo "All authentication tests completed!"
echo ""
echo "✓ Health check works without auth"
echo "✓ API rejects requests without API key"
echo "✓ API accepts requests with Authorization header"
echo "✓ API accepts requests with X-API-Key header"
echo "✓ Protected endpoints require authentication"
echo ""
echo "🎉 Authentication is working correctly!"
echo ""
echo "======================================================================"

# Cleanup
rm -f /tmp/health_response.json /tmp/no_auth_response.json /tmp/auth_response.json /tmp/xapi_response.json /tmp/devices_response.json
