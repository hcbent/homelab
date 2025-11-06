#!/usr/bin/env bash
#
# Terraform Infrastructure Validation Tests for nginx-lb HA Cluster
# Tests 1-8 for Task Group 2.1
#
# Usage: ./test-terraform.sh
#

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
PASSED=0
FAILED=0
TOTAL=8

# Function to print test results
print_result() {
    local test_num=$1
    local test_name=$2
    local result=$3
    local message=$4

    if [ "$result" = "PASS" ]; then
        echo -e "${GREEN}[PASS]${NC} Test $test_num: $test_name"
        ((PASSED++))
    else
        echo -e "${RED}[FAIL]${NC} Test $test_num: $test_name"
        echo -e "       ${message}"
        ((FAILED++))
    fi
}

echo "========================================"
echo "Nginx LB HA Terraform Validation Tests"
echo "========================================"
echo ""

# Test 1: Validate terraform configuration syntax
echo "Running Test 1: Terraform syntax validation..."
if terraform validate > /dev/null 2>&1; then
    print_result 1 "Terraform validate" "PASS" ""
else
    print_result 1 "Terraform validate" "FAIL" "Terraform configuration has syntax errors"
fi
echo ""

# Test 2: Verify both VMs are defined in plan output
echo "Running Test 2: Verify both VMs are defined..."
terraform plan -var-file=terraform.tfvars -out=/tmp/nginx-lb-plan > /tmp/nginx-lb-plan.txt 2>&1
vm_count=$(grep -c "module.nginx_lb_vms\[" /tmp/nginx-lb-plan.txt || echo "0")
if [ "$vm_count" -ge 2 ]; then
    print_result 2 "Both VMs defined in plan" "PASS" ""
else
    print_result 2 "Both VMs defined in plan" "FAIL" "Expected 2 VMs, found $vm_count"
fi
echo ""

# Test 3: Check correct IP addresses in plan (251, 252)
echo "Running Test 3: Verify IP addresses (251, 252)..."
if grep -q "192.168.10.251" /tmp/nginx-lb-plan.txt && grep -q "192.168.10.252" /tmp/nginx-lb-plan.txt; then
    print_result 3 "Correct IP addresses" "PASS" ""
else
    print_result 3 "Correct IP addresses" "FAIL" "Expected IPs 192.168.10.251 and 192.168.10.252"
fi
echo ""

# Test 4: Verify anti-affinity (different target_nodes)
echo "Running Test 4: Verify anti-affinity (different target_nodes)..."
has_pve1=$(grep -c "target_node.*=.*\"pve1\"" /tmp/nginx-lb-plan.txt || echo "0")
has_pve2=$(grep -c "target_node.*=.*\"pve2\"" /tmp/nginx-lb-plan.txt || echo "0")
if [ "$has_pve1" -ge 1 ] && [ "$has_pve2" -ge 1 ]; then
    print_result 4 "Anti-affinity (pve1, pve2)" "PASS" ""
else
    print_result 4 "Anti-affinity (pve1, pve2)" "FAIL" "Expected VMs on pve1 and pve2"
fi
echo ""

# Test 5: Confirm VMID assignments (250, 251)
echo "Running Test 5: Verify VMID assignments (250, 251)..."
if grep -q "vmid.*=.*250" /tmp/nginx-lb-plan.txt && grep -q "vmid.*=.*251" /tmp/nginx-lb-plan.txt; then
    print_result 5 "VMID assignments (250, 251)" "PASS" ""
else
    print_result 5 "VMID assignments (250, 251)" "FAIL" "Expected VMIDs 250 and 251"
fi
echo ""

# Test 6: Verify storage backend is "tank"
echo "Running Test 6: Verify storage backend is tank..."
tank_count=$(grep -c "disk_storage.*=.*\"tank\"" /tmp/nginx-lb-plan.txt || echo "0")
if [ "$tank_count" -ge 2 ]; then
    print_result 6 "Storage backend is tank" "PASS" ""
else
    print_result 6 "Storage backend is tank" "FAIL" "Expected storage=tank for both VMs"
fi
echo ""

# Test 7: Check tags are "nginx;loadbalancer;ha"
echo "Running Test 7: Verify tags are nginx;loadbalancer;ha..."
if grep -q "nginx;loadbalancer;ha" /tmp/nginx-lb-plan.txt; then
    print_result 7 "Tags are nginx;loadbalancer;ha" "PASS" ""
else
    print_result 7 "Tags are nginx;loadbalancer;ha" "FAIL" "Expected tags: nginx;loadbalancer;ha"
fi
echo ""

# Test 8: Validate cloud-init configuration references
echo "Running Test 8: Validate cloud-init configuration..."
ciuser_count=$(grep -c "ciuser" /tmp/nginx-lb-plan.txt || echo "0")
sshkeys_count=$(grep -c "sshkeys" /tmp/nginx-lb-plan.txt || echo "0")
if [ "$ciuser_count" -ge 1 ] && [ "$sshkeys_count" -ge 1 ]; then
    print_result 8 "Cloud-init configuration" "PASS" ""
else
    print_result 8 "Cloud-init configuration" "FAIL" "Cloud-init configuration not found"
fi
echo ""

# Clean up
rm -f /tmp/nginx-lb-plan /tmp/nginx-lb-plan.txt

# Print summary
echo "========================================"
echo "Test Summary"
echo "========================================"
echo -e "Total Tests: $TOTAL"
echo -e "${GREEN}Passed: $PASSED${NC}"
echo -e "${RED}Failed: $FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed. Please review the output above.${NC}"
    exit 1
fi
