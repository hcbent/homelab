#!/usr/bin/env bash
# Test script for nginx and HA configuration validation
# Task 4.1: Tests for nginx and Corosync configuration
#
# These tests validate:
# - Nginx installation and service status
# - Nginx configuration validity
# - Stream and HTTP blocks for dual-purpose operation
# - Corosync/Pacemaker cluster status
# - VIP resource configuration

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_INVENTORY="${SCRIPT_DIR}/inventory/lab"
TEST_COUNT=0
PASS_COUNT=0
FAIL_COUNT=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print test results
print_test() {
    local test_name=$1
    local result=$2
    local message=$3

    TEST_COUNT=$((TEST_COUNT + 1))

    if [ "$result" = "PASS" ]; then
        echo -e "${GREEN}[PASS]${NC} Test ${TEST_COUNT}: ${test_name}"
        PASS_COUNT=$((PASS_COUNT + 1))
    elif [ "$result" = "FAIL" ]; then
        echo -e "${RED}[FAIL]${NC} Test ${TEST_COUNT}: ${test_name}"
        echo -e "       ${message}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    else
        echo -e "${YELLOW}[SKIP]${NC} Test ${TEST_COUNT}: ${test_name} - ${message}"
    fi
}

# Function to check if VMs are provisioned
check_vms_provisioned() {
    echo "Checking if nginx-lb VMs are provisioned..."
    if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m ping &>/dev/null; then
        return 0
    else
        return 1
    fi
}

echo "========================================"
echo "Nginx and HA Configuration Tests"
echo "========================================"
echo ""

# Check if VMs are provisioned
if ! check_vms_provisioned; then
    echo -e "${YELLOW}WARNING:${NC} nginx-lb VMs are not yet provisioned or not accessible"
    echo "These tests require VMs to be running. Please run 'terraform apply' first."
    echo ""
    echo "All tests will be SKIPPED"
    echo ""
    for i in {1..8}; do
        case $i in
            1) print_test "Verify nginx installed and running on both nodes" "SKIP" "VMs not provisioned" ;;
            2) print_test "Check nginx configuration syntax valid (nginx -t)" "SKIP" "VMs not provisioned" ;;
            3) print_test "Validate stream block exists for K8s API (port 6443)" "SKIP" "VMs not provisioned" ;;
            4) print_test "Validate HTTP blocks exist for NodePort services" "SKIP" "VMs not provisioned" ;;
            5) print_test "Verify corosync service running on both nodes" "SKIP" "VMs not provisioned" ;;
            6) print_test "Check pacemaker service running on both nodes" "SKIP" "VMs not provisioned" ;;
            7) print_test "Validate VIP resource configured in cluster" "SKIP" "VMs not provisioned" ;;
            8) print_test "Confirm cluster shows 2 nodes online" "SKIP" "VMs not provisioned" ;;
        esac
    done
    echo ""
    echo "========================================"
    echo "Test Summary: ${TEST_COUNT} tests total"
    echo "SKIPPED: All tests (VMs not provisioned)"
    echo "========================================"
    exit 0
fi

echo "VMs are accessible. Running tests..."
echo ""

# Test 1: Verify nginx installed and running on both nodes
echo "Test 1: Checking nginx service status..."
if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "systemctl is-active nginx" -b 2>/dev/null | grep -q "SUCCESS"; then
    if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "systemctl is-active nginx" -b 2>/dev/null | grep -q "active"; then
        print_test "Verify nginx installed and running on both nodes" "PASS"
    else
        print_test "Verify nginx installed and running on both nodes" "FAIL" "Nginx service is not active"
    fi
else
    print_test "Verify nginx installed and running on both nodes" "FAIL" "Unable to check nginx service status"
fi

# Test 2: Check nginx configuration syntax valid (nginx -t)
echo "Test 2: Validating nginx configuration syntax..."
if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "nginx -t" -b 2>/dev/null | grep -q "syntax is ok"; then
    if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "nginx -t" -b 2>/dev/null | grep -q "test is successful"; then
        print_test "Check nginx configuration syntax valid (nginx -t)" "PASS"
    else
        print_test "Check nginx configuration syntax valid (nginx -t)" "FAIL" "Nginx configuration test failed"
    fi
else
    print_test "Check nginx configuration syntax valid (nginx -t)" "FAIL" "Nginx configuration syntax error"
fi

# Test 3: Validate stream block exists for K8s API (port 6443)
echo "Test 3: Checking for stream block (K8s API port 6443)..."
if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "grep -q 'stream {' /etc/nginx/nginx.conf || grep -q 'stream {' /etc/nginx/conf.d/*.conf" -b 2>/dev/null | grep -q "SUCCESS"; then
    if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "grep -q 'listen 6443' /etc/nginx/nginx.conf || grep -q 'listen 6443' /etc/nginx/conf.d/*.conf" -b 2>/dev/null | grep -q "SUCCESS"; then
        print_test "Validate stream block exists for K8s API (port 6443)" "PASS"
    else
        print_test "Validate stream block exists for K8s API (port 6443)" "FAIL" "Port 6443 not found in stream configuration"
    fi
else
    print_test "Validate stream block exists for K8s API (port 6443)" "FAIL" "Stream block not found in nginx configuration"
fi

# Test 4: Validate HTTP blocks exist for NodePort services
echo "Test 4: Checking for HTTP server blocks (NodePort services)..."
if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "grep -c 'listen 8080' /etc/nginx/conf.d/*.conf" -b 2>/dev/null | grep -q "[1-9]"; then
    if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "grep -c 'listen 80' /etc/nginx/conf.d/*.conf" -b 2>/dev/null | grep -q "[1-9]"; then
        print_test "Validate HTTP blocks exist for NodePort services" "PASS"
    else
        print_test "Validate HTTP blocks exist for NodePort services" "FAIL" "NodePort service HTTP blocks not complete"
    fi
else
    print_test "Validate HTTP blocks exist for NodePort services" "FAIL" "ArgoCD HTTP block not found"
fi

# Test 5: Verify corosync service running on both nodes
echo "Test 5: Checking corosync service status..."
if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "systemctl is-active corosync" -b 2>/dev/null | grep -q "SUCCESS"; then
    if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "systemctl is-active corosync" -b 2>/dev/null | grep -q "active"; then
        print_test "Verify corosync service running on both nodes" "PASS"
    else
        print_test "Verify corosync service running on both nodes" "FAIL" "Corosync service is not active"
    fi
else
    print_test "Verify corosync service running on both nodes" "FAIL" "Unable to check corosync service status"
fi

# Test 6: Check pacemaker service running on both nodes
echo "Test 6: Checking pacemaker service status..."
if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "systemctl is-active pacemaker" -b 2>/dev/null | grep -q "SUCCESS"; then
    if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "systemctl is-active pacemaker" -b 2>/dev/null | grep -q "active"; then
        print_test "Check pacemaker service running on both nodes" "PASS"
    else
        print_test "Check pacemaker service running on both nodes" "FAIL" "Pacemaker service is not active"
    fi
else
    print_test "Check pacemaker service running on both nodes" "FAIL" "Unable to check pacemaker service status"
fi

# Test 7: Validate VIP resource configured in cluster
echo "Test 7: Checking VIP resource configuration..."
if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "crm resource status cluster-vip" -b 2>/dev/null | grep -q "SUCCESS"; then
    if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "crm resource status cluster-vip" -b 2>/dev/null | grep -q "192.168.10.250"; then
        print_test "Validate VIP resource configured in cluster" "PASS"
    else
        print_test "Validate VIP resource configured in cluster" "FAIL" "VIP 192.168.10.250 not found in resource configuration"
    fi
else
    print_test "Validate VIP resource configured in cluster" "FAIL" "cluster-vip resource not found"
fi

# Test 8: Confirm cluster shows 2 nodes online
echo "Test 8: Checking cluster node count..."
if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "crm status | grep -c 'Online:'" -b 2>/dev/null | grep -q "SUCCESS"; then
    NODE_COUNT=$(ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "crm status | grep 'Online:' | head -1" -b 2>/dev/null | grep -oP '\[\K[^\]]+' | tr ' ' '\n' | wc -l)
    if [ "$NODE_COUNT" -ge 2 ] 2>/dev/null; then
        print_test "Confirm cluster shows 2 nodes online" "PASS"
    else
        print_test "Confirm cluster shows 2 nodes online" "FAIL" "Expected 2 nodes online, found different count"
    fi
else
    print_test "Confirm cluster shows 2 nodes online" "FAIL" "Unable to check cluster status"
fi

# Summary
echo ""
echo "========================================"
echo "Test Summary"
echo "========================================"
echo "Total tests: ${TEST_COUNT}"
echo -e "${GREEN}Passed: ${PASS_COUNT}${NC}"
echo -e "${RED}Failed: ${FAIL_COUNT}${NC}"
echo "========================================"

if [ $FAIL_COUNT -gt 0 ]; then
    exit 1
else
    exit 0
fi
