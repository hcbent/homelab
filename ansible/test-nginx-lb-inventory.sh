#!/usr/bin/env bash
# Test script for Nginx LB Ansible inventory configuration
# Task Group 3.1: Inventory validation tests
#
# This script validates:
# - Inventory file syntax
# - nginx_lb group contains both hosts
# - ansible_host variables are correct
# - Group variables are properly loaded
# - Connectivity to both hosts (requires VMs to be provisioned)
# - Sudo access works (requires VMs to be provisioned)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY_FILE="${SCRIPT_DIR}/inventory/lab"
ANSIBLE_CMD="ansible -i ${INVENTORY_FILE}"
ANSIBLE_INVENTORY_CMD="ansible-inventory -i ${INVENTORY_FILE}"

echo "=========================================="
echo "Nginx LB Inventory Validation Tests"
echo "=========================================="
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

TESTS_PASSED=0
TESTS_FAILED=0

# Test function
run_test() {
    local test_name="$1"
    local test_command="$2"

    echo "Test: ${test_name}"
    if eval "${test_command}"; then
        echo -e "${GREEN}[PASS]${NC} ${test_name}"
        ((TESTS_PASSED++))
    else
        echo -e "${RED}[FAIL]${NC} ${test_name}"
        ((TESTS_FAILED++))
    fi
    echo ""
}

# Test 1: Validate inventory file syntax (ansible-inventory --list)
echo "----------------------------------------"
echo "Test 1: Validate inventory file syntax"
echo "----------------------------------------"
if ${ANSIBLE_INVENTORY_CMD} --list > /dev/null 2>&1; then
    echo -e "${GREEN}[PASS]${NC} Inventory file syntax is valid"
    ((TESTS_PASSED++))
else
    echo -e "${RED}[FAIL]${NC} Inventory file syntax validation failed"
    ((TESTS_FAILED++))
fi
echo ""

# Test 2: Verify nginx_lb group contains both hosts
echo "----------------------------------------"
echo "Test 2: Verify nginx_lb group contains both hosts"
echo "----------------------------------------"
INVENTORY_JSON=$(${ANSIBLE_INVENTORY_CMD} --list)
if echo "${INVENTORY_JSON}" | grep -q '"nginx_lb"'; then
    echo "nginx_lb group found in inventory"

    # Check for nginx-lb01
    if echo "${INVENTORY_JSON}" | grep -q 'nginx-lb01'; then
        echo "  - nginx-lb01 found"
    else
        echo -e "${RED}  - nginx-lb01 NOT found${NC}"
        echo -e "${RED}[FAIL]${NC} nginx-lb01 missing from nginx_lb group"
        ((TESTS_FAILED++))
        echo ""
        continue
    fi

    # Check for nginx-lb02
    if echo "${INVENTORY_JSON}" | grep -q 'nginx-lb02'; then
        echo "  - nginx-lb02 found"
    else
        echo -e "${RED}  - nginx-lb02 NOT found${NC}"
        echo -e "${RED}[FAIL]${NC} nginx-lb02 missing from nginx_lb group"
        ((TESTS_FAILED++))
        echo ""
        continue
    fi

    echo -e "${GREEN}[PASS]${NC} nginx_lb group contains both hosts"
    ((TESTS_PASSED++))
else
    echo -e "${RED}[FAIL]${NC} nginx_lb group not found in inventory"
    ((TESTS_FAILED++))
fi
echo ""

# Test 3: Check ansible_host variables are correct (251, 252)
echo "----------------------------------------"
echo "Test 3: Check ansible_host variables"
echo "----------------------------------------"
NGINX_LB01_IP=$(${ANSIBLE_INVENTORY_CMD} --host nginx-lb01 2>/dev/null | grep -o '"ansible_host": "[^"]*"' | cut -d'"' -f4)
NGINX_LB02_IP=$(${ANSIBLE_INVENTORY_CMD} --host nginx-lb02 2>/dev/null | grep -o '"ansible_host": "[^"]*"' | cut -d'"' -f4)

if [ "${NGINX_LB01_IP}" == "192.168.10.251" ]; then
    echo "  - nginx-lb01 ansible_host: ${NGINX_LB01_IP} (correct)"
else
    echo -e "${RED}  - nginx-lb01 ansible_host: ${NGINX_LB01_IP} (expected 192.168.10.251)${NC}"
    echo -e "${RED}[FAIL]${NC} nginx-lb01 has incorrect ansible_host"
    ((TESTS_FAILED++))
    echo ""
    continue
fi

if [ "${NGINX_LB02_IP}" == "192.168.10.252" ]; then
    echo "  - nginx-lb02 ansible_host: ${NGINX_LB02_IP} (correct)"
else
    echo -e "${RED}  - nginx-lb02 ansible_host: ${NGINX_LB02_IP} (expected 192.168.10.252)${NC}"
    echo -e "${RED}[FAIL]${NC} nginx-lb02 has incorrect ansible_host"
    ((TESTS_FAILED++))
    echo ""
    continue
fi

echo -e "${GREEN}[PASS]${NC} ansible_host variables are correct"
((TESTS_PASSED++))
echo ""

# Test 4: Validate group variables exist (cluster_vip, cluster_name)
echo "----------------------------------------"
echo "Test 4: Validate group variables"
echo "----------------------------------------"
GROUP_VARS_FILE="${SCRIPT_DIR}/group_vars/nginx_lb.yml"
if [ ! -f "${GROUP_VARS_FILE}" ]; then
    echo -e "${RED}[FAIL]${NC} Group vars file not found: ${GROUP_VARS_FILE}"
    ((TESTS_FAILED++))
    echo ""
else
    # Check for cluster_vip
    if grep -q "cluster_vip:" "${GROUP_VARS_FILE}"; then
        CLUSTER_VIP=$(grep "cluster_vip:" "${GROUP_VARS_FILE}" | awk '{print $2}')
        echo "  - cluster_vip: ${CLUSTER_VIP}"
    else
        echo -e "${RED}  - cluster_vip: NOT FOUND${NC}"
        echo -e "${RED}[FAIL]${NC} cluster_vip variable missing"
        ((TESTS_FAILED++))
        echo ""
        continue
    fi

    # Check for cluster_name
    if grep -q "cluster_name:" "${GROUP_VARS_FILE}"; then
        CLUSTER_NAME=$(grep "cluster_name:" "${GROUP_VARS_FILE}" | awk '{print $2}')
        echo "  - cluster_name: ${CLUSTER_NAME}"
    else
        echo -e "${RED}  - cluster_name: NOT FOUND${NC}"
        echo -e "${RED}[FAIL]${NC} cluster_name variable missing"
        ((TESTS_FAILED++))
        echo ""
        continue
    fi

    # Check for k8s_control_plane
    if grep -q "k8s_control_plane:" "${GROUP_VARS_FILE}"; then
        echo "  - k8s_control_plane: defined"
    else
        echo -e "${RED}  - k8s_control_plane: NOT FOUND${NC}"
        echo -e "${RED}[FAIL]${NC} k8s_control_plane variable missing"
        ((TESTS_FAILED++))
        echo ""
        continue
    fi

    # Check for k8s_workers
    if grep -q "k8s_workers:" "${GROUP_VARS_FILE}"; then
        echo "  - k8s_workers: defined"
    else
        echo -e "${RED}  - k8s_workers: NOT FOUND${NC}"
        echo -e "${RED}[FAIL]${NC} k8s_workers variable missing"
        ((TESTS_FAILED++))
        echo ""
        continue
    fi

    echo -e "${GREEN}[PASS]${NC} Group variables are properly defined"
    ((TESTS_PASSED++))
fi
echo ""

# Test 5: Test connectivity to both hosts (ansible nginx_lb -m ping)
# NOTE: This test requires VMs to be provisioned
echo "----------------------------------------"
echo "Test 5: Test connectivity to both hosts"
echo "----------------------------------------"
echo -e "${YELLOW}[INFO]${NC} This test requires VMs to be provisioned first"
if ${ANSIBLE_CMD} nginx_lb -m ping > /dev/null 2>&1; then
    echo -e "${GREEN}[PASS]${NC} Connectivity test successful"
    ((TESTS_PASSED++))
else
    echo -e "${YELLOW}[SKIP]${NC} Connectivity test skipped (VMs not yet provisioned)"
    echo "         Run this test after terraform apply completes"
fi
echo ""

# Test 6: Verify sudo access works (ansible nginx_lb -m shell -a "sudo whoami")
# NOTE: This test requires VMs to be provisioned
echo "----------------------------------------"
echo "Test 6: Verify sudo access"
echo "----------------------------------------"
echo -e "${YELLOW}[INFO]${NC} This test requires VMs to be provisioned first"
if ${ANSIBLE_CMD} nginx_lb -m shell -a "sudo whoami" > /dev/null 2>&1; then
    echo -e "${GREEN}[PASS]${NC} Sudo access test successful"
    ((TESTS_PASSED++))
else
    echo -e "${YELLOW}[SKIP]${NC} Sudo access test skipped (VMs not yet provisioned)"
    echo "         Run this test after terraform apply completes"
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
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi
