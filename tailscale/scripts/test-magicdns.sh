#!/bin/bash
#
# test-magicdns.sh - Test MagicDNS resolution for Tailscale homelab
#
# This script tests DNS resolution from a Tailscale-connected device
# to verify MagicDNS is working correctly.
#
# Usage: ./test-magicdns.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
TAILNET_NAME="shire-pangolin.ts.net"
K8S_OPERATOR_HOSTNAME="k8s-operator-homelab"
K8S_OPERATOR_IP="100.111.93.96"

echo "============================================"
echo "MagicDNS Test Script for Tailscale Homelab"
echo "============================================"
echo ""
echo "Tailnet: ${TAILNET_NAME}"
echo "Date: $(date)"
echo ""

# Track test results
TESTS_PASSED=0
TESTS_FAILED=0

# Function to run a test
run_test() {
    local test_name="$1"
    local command="$2"

    echo -n "Testing: ${test_name}... "

    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}PASS${NC}"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}FAIL${NC}"
        ((TESTS_FAILED++))
        return 1
    fi
}

# Function to show detailed output for a test
show_test_output() {
    local test_name="$1"
    local command="$2"

    echo ""
    echo "--- ${test_name} ---"
    eval "$command" 2>&1 || true
    echo ""
}

echo "============================================"
echo "1. Checking Tailscale Connection"
echo "============================================"
echo ""

# Check if Tailscale is installed
if ! command -v tailscale &> /dev/null; then
    echo -e "${RED}ERROR: Tailscale is not installed or not in PATH${NC}"
    echo "Please install Tailscale and try again."
    exit 1
fi

# Check Tailscale connection status
echo "Current Tailscale status:"
tailscale status 2>&1 || {
    echo -e "${RED}ERROR: Cannot get Tailscale status${NC}"
    echo "Make sure Tailscale is running and you are connected."
    exit 1
}
echo ""

# Verify we're connected
if ! tailscale status | grep -q "${K8S_OPERATOR_IP}"; then
    echo -e "${YELLOW}WARNING: K8s operator (${K8S_OPERATOR_IP}) not visible in status${NC}"
    echo "The operator may not be connected or you may not be connected to Tailscale."
fi

echo "============================================"
echo "2. Testing MagicDNS Resolution"
echo "============================================"
echo ""

# Test 1: Resolve K8s operator by full FQDN
run_test "Resolve ${K8S_OPERATOR_HOSTNAME}.${TAILNET_NAME}" \
    "ping -c 1 -t 5 ${K8S_OPERATOR_HOSTNAME}.${TAILNET_NAME}"

# Test 2: Resolve K8s operator by short name (if MagicDNS search domain is set)
run_test "Resolve ${K8S_OPERATOR_HOSTNAME} (short name)" \
    "ping -c 1 -t 5 ${K8S_OPERATOR_HOSTNAME}"

# Test 3: Ping K8s operator by IP
run_test "Ping ${K8S_OPERATOR_IP} (direct IP)" \
    "ping -c 1 -t 5 ${K8S_OPERATOR_IP}"

echo ""
echo "============================================"
echo "3. Testing External DNS Resolution"
echo "============================================"
echo ""

# Test 4: Resolve google.com
run_test "Resolve google.com" \
    "ping -c 1 -t 5 google.com"

# Test 5: Resolve github.com
run_test "Resolve github.com" \
    "ping -c 1 -t 5 github.com"

# Test 6: Resolve cloudflare.com
run_test "Resolve cloudflare.com" \
    "ping -c 1 -t 5 cloudflare.com"

echo ""
echo "============================================"
echo "4. DNS Lookup Details"
echo "============================================"

# Show DNS lookup for K8s operator
echo ""
echo "DNS lookup for ${K8S_OPERATOR_HOSTNAME}.${TAILNET_NAME}:"
nslookup "${K8S_OPERATOR_HOSTNAME}.${TAILNET_NAME}" 2>&1 || echo "nslookup failed"

# Show DNS lookup for external domain
echo ""
echo "DNS lookup for google.com:"
nslookup google.com 2>&1 || echo "nslookup failed"

echo ""
echo "============================================"
echo "5. System DNS Configuration"
echo "============================================"

# Show DNS resolver info (macOS specific)
if [[ "$(uname)" == "Darwin" ]]; then
    echo ""
    echo "macOS DNS configuration (Tailscale entries):"
    scutil --dns 2>&1 | grep -A 10 "Tailscale" || echo "No Tailscale DNS entries found"
fi

echo ""
echo "============================================"
echo "6. Test Summary"
echo "============================================"
echo ""

TOTAL_TESTS=$((TESTS_PASSED + TESTS_FAILED))
echo "Tests passed: ${TESTS_PASSED}/${TOTAL_TESTS}"

if [ ${TESTS_FAILED} -eq 0 ]; then
    echo -e "${GREEN}All tests passed! MagicDNS is working correctly.${NC}"
    exit 0
else
    echo -e "${RED}${TESTS_FAILED} test(s) failed.${NC}"
    echo ""
    echo "Troubleshooting steps:"
    echo "1. Verify MagicDNS is enabled in Tailscale admin console"
    echo "2. Check that your device is connected to Tailscale"
    echo "3. Restart Tailscale: sudo killall tailscaled (macOS)"
    echo "4. Flush DNS cache: sudo dscacheutil -flushcache (macOS)"
    exit 1
fi
