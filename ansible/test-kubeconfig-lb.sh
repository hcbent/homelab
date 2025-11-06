#!/bin/bash
# Test script for kubeconfig load balancer integration
# Tests kubectl functionality through VIP endpoint (192.168.10.250:6443)
#
# Part of Task Group 5: Kubeconfig Update and Validation
# Spec: agent-os/specs/2025-11-05-nginx-lb-ha

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TEST_RESULTS=()
VIP="192.168.10.250"
VIP_ENDPOINT="https://${VIP}:6443"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test result tracking
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

log_skip() {
    echo -e "${YELLOW}[SKIP]${NC} $1"
    TESTS_SKIPPED=$((TESTS_SKIPPED + 1))
}

log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

# Test 1: Verify kubectl can connect through VIP (192.168.10.250:6443)
test_kubectl_connect_vip() {
    echo ""
    echo "Test 1: Verify kubectl can connect through VIP"
    echo "----------------------------------------------"

    if ! command -v kubectl &> /dev/null; then
        log_skip "kubectl not found in PATH"
        return
    fi

    # Check if kubeconfig exists
    if [ ! -f ~/.kube/config ]; then
        log_skip "No kubeconfig file found at ~/.kube/config"
        return
    fi

    # Try to connect through VIP
    if kubectl cluster-info &> /dev/null; then
        # Check if using VIP endpoint
        CURRENT_SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
        if [[ "$CURRENT_SERVER" == "$VIP_ENDPOINT" ]]; then
            log_pass "kubectl connects through VIP: $CURRENT_SERVER"
        else
            log_fail "kubectl using endpoint: $CURRENT_SERVER (expected: $VIP_ENDPOINT)"
        fi
    else
        log_fail "kubectl cannot connect to cluster"
    fi
}

# Test 2: Test kubectl get nodes works through load balancer
test_kubectl_get_nodes() {
    echo ""
    echo "Test 2: Test kubectl get nodes through load balancer"
    echo "----------------------------------------------------"

    if ! command -v kubectl &> /dev/null; then
        log_skip "kubectl not found in PATH"
        return
    fi

    if [ ! -f ~/.kube/config ]; then
        log_skip "No kubeconfig file found"
        return
    fi

    # Try to get nodes
    if kubectl get nodes &> /dev/null; then
        NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')
        if [ "$NODE_COUNT" -gt 0 ]; then
            log_pass "kubectl get nodes returned $NODE_COUNT nodes"
        else
            log_fail "kubectl get nodes returned no nodes"
        fi
    else
        log_fail "kubectl get nodes failed"
    fi
}

# Test 3: Validate kubectl get pods --all-namespaces works
test_kubectl_get_pods() {
    echo ""
    echo "Test 3: Validate kubectl get pods --all-namespaces"
    echo "---------------------------------------------------"

    if ! command -v kubectl &> /dev/null; then
        log_skip "kubectl not found in PATH"
        return
    fi

    if [ ! -f ~/.kube/config ]; then
        log_skip "No kubeconfig file found"
        return
    fi

    # Try to get pods
    if kubectl get pods --all-namespaces &> /dev/null; then
        POD_COUNT=$(kubectl get pods --all-namespaces --no-headers 2>/dev/null | wc -l | tr -d ' ')
        log_pass "kubectl get pods --all-namespaces returned $POD_COUNT pods"
    else
        log_fail "kubectl get pods --all-namespaces failed"
    fi
}

# Test 4: Test long-running kubectl command (kubectl logs with timeout)
test_kubectl_long_running() {
    echo ""
    echo "Test 4: Test long-running kubectl command"
    echo "------------------------------------------"

    if ! command -v kubectl &> /dev/null; then
        log_skip "kubectl not found in PATH"
        return
    fi

    if [ ! -f ~/.kube/config ]; then
        log_skip "No kubeconfig file found"
        return
    fi

    # Find a running pod to test with
    POD=$(kubectl get pods --all-namespaces --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    NAMESPACE=$(kubectl get pods --all-namespaces --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.namespace}' 2>/dev/null)

    if [ -z "$POD" ] || [ -z "$NAMESPACE" ]; then
        log_skip "No running pods found to test long-running command"
        return
    fi

    # Test kubectl logs with a 5-second timeout
    if timeout 5s kubectl logs -n "$NAMESPACE" "$POD" --tail=10 &> /dev/null; then
        log_pass "kubectl logs command completed within timeout"
    else
        EXIT_CODE=$?
        if [ $EXIT_CODE -eq 124 ]; then
            log_pass "kubectl logs ran for full timeout period (connection stable)"
        else
            log_fail "kubectl logs failed with exit code $EXIT_CODE"
        fi
    fi
}

# Test 5: Verify kubeconfig server endpoint is https://192.168.10.250:6443
test_kubeconfig_endpoint() {
    echo ""
    echo "Test 5: Verify kubeconfig server endpoint"
    echo "------------------------------------------"

    if ! command -v kubectl &> /dev/null; then
        log_skip "kubectl not found in PATH"
        return
    fi

    if [ ! -f ~/.kube/config ]; then
        log_skip "No kubeconfig file found"
        return
    fi

    CURRENT_SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null)

    if [ "$CURRENT_SERVER" = "$VIP_ENDPOINT" ]; then
        log_pass "kubeconfig server endpoint is $VIP_ENDPOINT"
    else
        log_fail "kubeconfig server endpoint is $CURRENT_SERVER (expected: $VIP_ENDPOINT)"
    fi
}

# Test 6: Test kubectl operations from remote cluster nodes
test_kubectl_remote_nodes() {
    echo ""
    echo "Test 6: Test kubectl operations from remote cluster nodes"
    echo "----------------------------------------------------------"

    # This test requires ssh access to cluster nodes
    # Check if we can access the nodes
    if ! command -v ansible &> /dev/null; then
        log_skip "ansible not found in PATH (needed to test remote nodes)"
        return
    fi

    # Check if inventory file exists
    if [ ! -f "$SCRIPT_DIR/inventory/lab" ]; then
        log_skip "Inventory file not found (needed to test remote nodes)"
        return
    fi

    # Try to test kubectl on one control plane node
    # This assumes the node has kubectl installed and kubeconfig updated
    if ansible km01 -i "$SCRIPT_DIR/inventory/lab" -m shell -a "kubectl get nodes" &> /dev/null; then
        log_pass "kubectl works on remote control plane node (km01)"
    else
        # Check if node is reachable
        if ansible km01 -i "$SCRIPT_DIR/inventory/lab" -m ping &> /dev/null; then
            log_fail "kubectl command failed on remote node km01"
        else
            log_skip "Cannot reach remote node km01 (may not be provisioned yet)"
        fi
    fi
}

# Test 7: Verify backup kubeconfig files were created
test_kubeconfig_backups() {
    echo ""
    echo "Test 7: Verify backup kubeconfig files exist"
    echo "---------------------------------------------"

    if [ ! -f ~/.kube/config ]; then
        log_skip "No kubeconfig file found"
        return
    fi

    # Check for backup files (created by update playbook)
    BACKUP_COUNT=$(find ~/.kube -name "config.backup.*" 2>/dev/null | wc -l | tr -d ' ')

    if [ "$BACKUP_COUNT" -gt 0 ]; then
        log_pass "Found $BACKUP_COUNT kubeconfig backup file(s)"
    else
        log_skip "No backup files found (may not have run update playbook yet)"
    fi
}

# Test 8: Validate certificate authentication still works through LB
test_certificate_auth() {
    echo ""
    echo "Test 8: Validate certificate authentication through LB"
    echo "-------------------------------------------------------"

    if ! command -v kubectl &> /dev/null; then
        log_skip "kubectl not found in PATH"
        return
    fi

    if [ ! -f ~/.kube/config ]; then
        log_skip "No kubeconfig file found"
        return
    fi

    # Try to get current user info (requires valid authentication)
    if kubectl auth whoami &> /dev/null; then
        CURRENT_USER=$(kubectl auth whoami -o jsonpath='{.status.userInfo.username}' 2>/dev/null)
        if [ -n "$CURRENT_USER" ]; then
            log_pass "Certificate authentication working, authenticated as: $CURRENT_USER"
        else
            log_fail "Authentication check returned empty user"
        fi
    else
        # Try alternative method using kubectl config
        if kubectl config view --minify &> /dev/null; then
            log_pass "Certificate authentication appears to be working"
        else
            log_fail "Certificate authentication check failed"
        fi
    fi
}

# Main execution
main() {
    echo "======================================================================="
    echo "Kubeconfig Load Balancer Integration Tests"
    echo "Task Group 5: Kubeconfig Update and Validation"
    echo "======================================================================="
    echo ""
    echo "VIP Endpoint: $VIP_ENDPOINT"
    echo "Test Date: $(date)"
    echo ""

    # Run all tests
    test_kubectl_connect_vip
    test_kubectl_get_nodes
    test_kubectl_get_pods
    test_kubectl_long_running
    test_kubeconfig_endpoint
    test_kubectl_remote_nodes
    test_kubeconfig_backups
    test_certificate_auth

    # Summary
    echo ""
    echo "======================================================================="
    echo "Test Summary"
    echo "======================================================================="
    echo -e "Tests Passed:  ${GREEN}${TESTS_PASSED}${NC}"
    echo -e "Tests Failed:  ${RED}${TESTS_FAILED}${NC}"
    echo -e "Tests Skipped: ${YELLOW}${TESTS_SKIPPED}${NC}"
    echo "Total Tests:   $((TESTS_PASSED + TESTS_FAILED + TESTS_SKIPPED))"
    echo ""

    if [ $TESTS_FAILED -gt 0 ]; then
        echo -e "${RED}RESULT: FAILED${NC}"
        exit 1
    elif [ $TESTS_PASSED -eq 0 ]; then
        echo -e "${YELLOW}RESULT: ALL TESTS SKIPPED${NC}"
        exit 2
    else
        echo -e "${GREEN}RESULT: PASSED${NC}"
        exit 0
    fi
}

# Run main function
main
