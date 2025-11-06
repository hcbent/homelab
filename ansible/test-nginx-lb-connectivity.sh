#!/usr/bin/env bash
# Connectivity test script for Nginx LB nodes
# Task Group 3.5 & 3.6: Basic connectivity and validation tests
#
# PREREQUISITE: VMs must be provisioned via terraform apply first
#
# This script tests:
# - Ansible ping connectivity to both nodes
# - SSH key authentication
# - Sudo access on both nodes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY_FILE="${SCRIPT_DIR}/inventory/lab"
ANSIBLE_CMD="ansible -i ${INVENTORY_FILE}"

echo "=========================================="
echo "Nginx LB Connectivity Tests"
echo "=========================================="
echo ""
echo "PREREQUISITE: VMs must be provisioned first"
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

TESTS_PASSED=0
TESTS_FAILED=0

# Test 1: Ansible ping to both hosts
echo "----------------------------------------"
echo "Test 1: Ansible ping to both hosts"
echo "----------------------------------------"
if ${ANSIBLE_CMD} nginx_lb -m ping; then
    echo ""
    echo -e "${GREEN}[PASS]${NC} Both nodes are reachable via ansible ping"
    ((TESTS_PASSED++))
else
    echo ""
    echo -e "${RED}[FAIL]${NC} Failed to reach one or more nodes"
    ((TESTS_FAILED++))
fi
echo ""

# Test 2: Test individual node connectivity
echo "----------------------------------------"
echo "Test 2: Test individual node connectivity"
echo "----------------------------------------"
echo "Testing nginx-lb01..."
if ${ANSIBLE_CMD} nginx-lb01 -m ping > /dev/null 2>&1; then
    echo -e "${GREEN}[PASS]${NC} nginx-lb01 is reachable"
    ((TESTS_PASSED++))
else
    echo -e "${RED}[FAIL]${NC} nginx-lb01 is NOT reachable"
    ((TESTS_FAILED++))
fi

echo "Testing nginx-lb02..."
if ${ANSIBLE_CMD} nginx-lb02 -m ping > /dev/null 2>&1; then
    echo -e "${GREEN}[PASS]${NC} nginx-lb02 is reachable"
    ((TESTS_PASSED++))
else
    echo -e "${RED}[FAIL]${NC} nginx-lb02 is NOT reachable"
    ((TESTS_FAILED++))
fi
echo ""

# Test 3: Verify sudo access
echo "----------------------------------------"
echo "Test 3: Verify sudo access on both nodes"
echo "----------------------------------------"
if ${ANSIBLE_CMD} nginx_lb -m shell -a "sudo whoami"; then
    echo ""
    echo -e "${GREEN}[PASS]${NC} Sudo access verified on both nodes"
    ((TESTS_PASSED++))
else
    echo ""
    echo -e "${RED}[FAIL]${NC} Sudo access failed on one or more nodes"
    ((TESTS_FAILED++))
fi
echo ""

# Test 4: Check SSH key authentication
echo "----------------------------------------"
echo "Test 4: Verify SSH key authentication"
echo "----------------------------------------"
if ${ANSIBLE_CMD} nginx_lb -m shell -a "echo 'SSH key auth working'"; then
    echo ""
    echo -e "${GREEN}[PASS]${NC} SSH key authentication verified"
    ((TESTS_PASSED++))
else
    echo ""
    echo -e "${RED}[FAIL]${NC} SSH key authentication failed"
    ((TESTS_FAILED++))
fi
echo ""

# Test 5: Gather basic facts
echo "----------------------------------------"
echo "Test 5: Gather basic system facts"
echo "----------------------------------------"
if ${ANSIBLE_CMD} nginx_lb -m setup -a "filter=ansible_distribution*"; then
    echo ""
    echo -e "${GREEN}[PASS]${NC} System facts gathered successfully"
    ((TESTS_PASSED++))
else
    echo ""
    echo -e "${RED}[FAIL]${NC} Failed to gather system facts"
    ((TESTS_FAILED++))
fi
echo ""

# Test 6: Check disk space
echo "----------------------------------------"
echo "Test 6: Check disk space on both nodes"
echo "----------------------------------------"
if ${ANSIBLE_CMD} nginx_lb -m shell -a "df -h /"; then
    echo ""
    echo -e "${GREEN}[PASS]${NC} Disk space check completed"
    ((TESTS_PASSED++))
else
    echo ""
    echo -e "${RED}[FAIL]${NC} Disk space check failed"
    ((TESTS_FAILED++))
fi
echo ""

# Summary
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "Tests Passed: ${TESTS_PASSED}"
echo "Tests Failed: ${TESTS_FAILED}"
echo ""

if [ ${TESTS_FAILED} -eq 0 ]; then
    echo -e "${GREEN}All connectivity tests passed!${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Run the nginx and HA configuration playbook (Task Group 4)"
    echo "2. Verify corosync cluster formation"
    echo "3. Test VIP assignment and failover"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    echo ""
    echo "Troubleshooting steps:"
    echo "1. Verify VMs are running in Proxmox"
    echo "2. Check network connectivity: ping 192.168.10.251 and 192.168.10.252"
    echo "3. Verify SSH keys are deployed via cloud-init"
    echo "4. Check ansible_user is set correctly in inventory"
    echo "5. Review /var/log/cloud-init.log on VMs if cloud-init failed"
    exit 1
fi
