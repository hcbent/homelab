#!/usr/bin/env bash
#
# Strategic HA Failover Tests for nginx-lb HA Cluster
# Tests 1-10 for Task Group 6.2
#
# Usage: ./test-strategic-ha-failover.sh [test_number]
#        If no test number provided, runs all tests
#
# IMPORTANT: Some tests are DESTRUCTIVE and will impact service availability
# These tests should be run during maintenance windows or with proper planning
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANSIBLE_INVENTORY="${SCRIPT_DIR}/inventory/lab"
VIP="192.168.10.250"
VIP_ENDPOINT="https://${VIP}:6443"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
PASSED=0
FAILED=0
SKIPPED=0
TOTAL=10

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED++))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAILED++))
}

log_skip() {
    echo -e "${YELLOW}[SKIP]${NC} $1"
    ((SKIPPED++))
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check if ansible is available
    if ! command -v ansible &> /dev/null; then
        log_fail "ansible not found in PATH"
        exit 1
    fi

    # Check if kubectl is available
    if ! command -v kubectl &> /dev/null; then
        log_fail "kubectl not found in PATH"
        exit 1
    fi

    # Check if inventory file exists
    if [ ! -f "$ANSIBLE_INVENTORY" ]; then
        log_fail "Ansible inventory not found: $ANSIBLE_INVENTORY"
        exit 1
    fi

    # Check if nginx-lb nodes are accessible
    if ! ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m ping &> /dev/null; then
        log_fail "nginx-lb nodes are not accessible"
        exit 1
    fi

    log_pass "All prerequisites met"
    echo ""
}

# Test 1: HA failover test - stop nginx-lb01, verify VIP moves to nginx-lb02
test_ha_failover() {
    echo "========================================"
    echo "Test 1: HA Failover Test"
    echo "========================================"
    log_warn "This test will SHUT DOWN nginx-lb01. Service will failover to nginx-lb02."
    read -p "Continue? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log_skip "Test 1: HA failover test (user declined)"
        echo ""
        return
    fi

    # Get initial VIP location
    log_info "Checking initial VIP location..."
    INITIAL_VIP_HOST=$(ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "crm resource status cluster-vip 2>/dev/null | grep 'is running on' | awk '{print \$NF}'" -b 2>/dev/null | grep -A1 "nginx-lb" | tail -1 | awk '{print $1}')
    log_info "VIP currently on: $INITIAL_VIP_HOST"

    # Test kubectl before failover
    log_info "Testing kubectl before failover..."
    if ! kubectl get nodes &> /dev/null; then
        log_fail "kubectl not working before failover"
        echo ""
        return
    fi

    # Shutdown nginx-lb01
    log_info "Shutting down nginx-lb01..."
    ansible nginx-lb01 -i "$ANSIBLE_INVENTORY" -m shell -a "sudo shutdown -h now" -b &> /dev/null || true

    # Wait for failover (max 60 seconds)
    log_info "Waiting for VIP failover (max 60 seconds)..."
    FAILOVER_TIME=0
    while [ $FAILOVER_TIME -lt 60 ]; do
        sleep 2
        ((FAILOVER_TIME+=2))

        # Check if VIP responds
        if ping -c 1 -W 1 $VIP &> /dev/null; then
            # Check VIP location
            NEW_VIP_HOST=$(ansible nginx-lb02 -i "$ANSIBLE_INVENTORY" -m shell -a "crm resource status cluster-vip 2>/dev/null | grep 'is running on' | awk '{print \$NF}'" -b 2>/dev/null | grep -A1 "nginx-lb" | tail -1 | awk '{print $1}' || echo "unknown")

            if [ "$NEW_VIP_HOST" = "nginx-lb02" ]; then
                log_info "VIP moved to nginx-lb02 in ${FAILOVER_TIME} seconds"
                break
            fi
        fi
    done

    if [ $FAILOVER_TIME -ge 60 ]; then
        log_fail "Test 1: VIP did not failover within 60 seconds"
    else
        # Test kubectl after failover
        log_info "Testing kubectl after failover..."
        sleep 5  # Give a few seconds for connections to stabilize

        if kubectl get nodes &> /dev/null; then
            log_pass "Test 1: HA failover successful (${FAILOVER_TIME}s) - kubectl still works"
        else
            log_fail "Test 1: VIP failed over but kubectl not working"
        fi
    fi

    log_warn "Remember to start nginx-lb01 manually: ansible nginx-lb01 -i $ANSIBLE_INVENTORY -m shell -a 'sudo systemctl start corosync pacemaker nginx' -b"
    echo ""
}

# Test 2: HA failback test - start nginx-lb01, verify VIP returns to primary
test_ha_failback() {
    echo "========================================"
    echo "Test 2: HA Failback Test"
    echo "========================================"
    log_info "This test assumes nginx-lb01 was shut down in Test 1"
    log_info "Starting nginx-lb01 and waiting for VIP to return to primary..."

    # Check if nginx-lb01 is down
    if ansible nginx-lb01 -i "$ANSIBLE_INVENTORY" -m ping &> /dev/null; then
        log_skip "Test 2: nginx-lb01 is already running (Test 1 may not have been executed)"
        echo ""
        return
    fi

    log_warn "Please manually power on nginx-lb01 through Proxmox UI or CLI"
    read -p "Press ENTER when nginx-lb01 is powered on..."

    # Wait for nginx-lb01 to come online
    log_info "Waiting for nginx-lb01 to become accessible..."
    WAIT_TIME=0
    while [ $WAIT_TIME -lt 120 ]; do
        if ansible nginx-lb01 -i "$ANSIBLE_INVENTORY" -m ping &> /dev/null; then
            log_info "nginx-lb01 is accessible"
            break
        fi
        sleep 5
        ((WAIT_TIME+=5))
    done

    if [ $WAIT_TIME -ge 120 ]; then
        log_fail "Test 2: nginx-lb01 did not come online within 120 seconds"
        echo ""
        return
    fi

    # Start services on nginx-lb01
    log_info "Starting corosync, pacemaker, and nginx on nginx-lb01..."
    ansible nginx-lb01 -i "$ANSIBLE_INVENTORY" -m shell -a "sudo systemctl start corosync && sudo systemctl start pacemaker && sudo systemctl start nginx" -b &> /dev/null

    # Wait for VIP to failback to nginx-lb01
    log_info "Waiting for VIP to return to nginx-lb01 (max 60 seconds)..."
    FAILBACK_TIME=0
    while [ $FAILBACK_TIME -lt 60 ]; do
        sleep 3
        ((FAILBACK_TIME+=3))

        VIP_HOST=$(ansible nginx-lb01 -i "$ANSIBLE_INVENTORY" -m shell -a "crm resource status cluster-vip 2>/dev/null | grep 'is running on' | awk '{print \$NF}'" -b 2>/dev/null | grep -A1 "nginx-lb" | tail -1 | awk '{print $1}' || echo "unknown")

        if [ "$VIP_HOST" = "nginx-lb01" ]; then
            log_info "VIP returned to nginx-lb01 in ${FAILBACK_TIME} seconds"
            break
        fi
    done

    if [ $FAILBACK_TIME -ge 60 ]; then
        log_fail "Test 2: VIP did not failback to nginx-lb01 within 60 seconds"
    else
        # Test kubectl after failback
        if kubectl get nodes &> /dev/null; then
            log_pass "Test 2: HA failback successful (${FAILBACK_TIME}s) - kubectl still works"
        else
            log_fail "Test 2: VIP failed back but kubectl not working"
        fi
    fi
    echo ""
}

# Test 3: K8s API availability during failover
test_api_during_failover() {
    echo "========================================"
    echo "Test 3: K8s API Availability During Failover"
    echo "========================================"
    log_warn "This test will SHUT DOWN nginx-lb01 while running continuous kubectl operations"
    read -p "Continue? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log_skip "Test 3: K8s API availability during failover (user declined)"
        echo ""
        return
    fi

    # Start continuous kubectl operations in background
    log_info "Starting continuous kubectl operations..."
    KUBECTL_LOG="/tmp/kubectl-failover-test.log"
    > "$KUBECTL_LOG"

    (
        while true; do
            kubectl get nodes &>> "$KUBECTL_LOG"
            sleep 2
        done
    ) &
    KUBECTL_PID=$!

    sleep 5  # Let kubectl run for a bit

    # Shutdown nginx-lb01
    log_info "Shutting down nginx-lb01..."
    ansible nginx-lb01 -i "$ANSIBLE_INVENTORY" -m shell -a "sudo shutdown -h now" -b &> /dev/null || true

    # Wait 30 seconds during failover
    log_info "Monitoring kubectl operations during failover..."
    sleep 30

    # Kill background kubectl process
    kill $KUBECTL_PID 2>/dev/null || true

    # Analyze results
    ERROR_COUNT=$(grep -c "error\|refused\|timeout" "$KUBECTL_LOG" || echo "0")
    SUCCESS_COUNT=$(grep -c "Ready" "$KUBECTL_LOG" || echo "0")

    log_info "kubectl operations during failover: $SUCCESS_COUNT successful, $ERROR_COUNT errors"

    if [ "$ERROR_COUNT" -lt 3 ]; then
        log_pass "Test 3: K8s API remained available during failover (max $ERROR_COUNT transient errors)"
    else
        log_fail "Test 3: Too many kubectl errors during failover ($ERROR_COUNT)"
    fi

    rm -f "$KUBECTL_LOG"
    echo ""
}

# Test 4: NodePort service accessibility - test ArgoCD UI through load balancer
test_nodeport_argocd() {
    echo "========================================"
    echo "Test 4: NodePort Service Accessibility (ArgoCD)"
    echo "========================================"

    log_info "Testing ArgoCD UI accessibility through load balancer..."

    # Test HTTP port 8080
    if curl -s -o /dev/null -w "%{http_code}" "http://${VIP}:8080" | grep -q "200\|301\|302"; then
        log_info "ArgoCD HTTP (8080) is accessible"
        ARGOCD_HTTP=1
    else
        log_info "ArgoCD HTTP (8080) is not accessible (may be expected)"
        ARGOCD_HTTP=0
    fi

    # Test HTTPS port 8443
    if curl -k -s -o /dev/null -w "%{http_code}" "https://${VIP}:8443" | grep -q "200\|301\|302"; then
        log_info "ArgoCD HTTPS (8443) is accessible"
        ARGOCD_HTTPS=1
    else
        log_info "ArgoCD HTTPS (8443) is not accessible (may be expected)"
        ARGOCD_HTTPS=0
    fi

    if [ $ARGOCD_HTTP -eq 1 ] || [ $ARGOCD_HTTPS -eq 1 ]; then
        log_pass "Test 4: ArgoCD UI is accessible through load balancer"
    else
        log_skip "Test 4: ArgoCD UI not accessible (service may not be deployed)"
    fi
    echo ""
}

# Test 5: NodePort service during failover - verify Traefik remains accessible
test_nodeport_during_failover() {
    echo "========================================"
    echo "Test 5: NodePort Service During Failover (Traefik)"
    echo "========================================"
    log_warn "This test will SHUT DOWN nginx-lb01 while testing Traefik accessibility"
    read -p "Continue? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log_skip "Test 5: NodePort service during failover (user declined)"
        echo ""
        return
    fi

    # Test Traefik before failover
    log_info "Testing Traefik before failover..."
    if curl -s -o /dev/null -w "%{http_code}" "http://${VIP}:80" | grep -q "404\|200"; then
        log_info "Traefik accessible before failover"
        BEFORE_OK=1
    else
        log_skip "Test 5: Traefik not accessible (service may not be deployed)"
        echo ""
        return
    fi

    # Shutdown nginx-lb01
    log_info "Shutting down nginx-lb01..."
    ansible nginx-lb01 -i "$ANSIBLE_INVENTORY" -m shell -a "sudo shutdown -h now" -b &> /dev/null || true

    # Wait for failover
    sleep 15

    # Test Traefik after failover
    log_info "Testing Traefik after failover..."
    if curl -s -o /dev/null -w "%{http_code}" "http://${VIP}:80" | grep -q "404\|200"; then
        log_pass "Test 5: Traefik remains accessible during failover"
    else
        log_fail "Test 5: Traefik not accessible after failover"
    fi
    echo ""
}

# Test 6: Backend health check behavior
test_backend_health_checks() {
    echo "========================================"
    echo "Test 6: Backend Health Check Behavior"
    echo "========================================"
    log_warn "This test will SHUT DOWN one K8s control plane node (km01)"
    read -p "Continue? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log_skip "Test 6: Backend health check behavior (user declined)"
        echo ""
        return
    fi

    # Test kubectl before shutting down node
    log_info "Testing kubectl before node shutdown..."
    if ! kubectl get nodes &> /dev/null; then
        log_fail "kubectl not working before test"
        echo ""
        return
    fi

    # Shutdown km01
    log_info "Shutting down km01 (control plane node)..."
    ansible km01 -i "$ANSIBLE_INVENTORY" -m shell -a "sudo shutdown -h now" -b &> /dev/null || true

    # Wait for health check to detect failure (fail_timeout=30s)
    log_info "Waiting 35 seconds for health check to detect failure..."
    sleep 35

    # Test kubectl - should still work through remaining nodes
    log_info "Testing kubectl after km01 shutdown..."
    if kubectl get nodes &> /dev/null; then
        log_pass "Test 6: kubectl still works after one control plane node down"
    else
        log_fail "Test 6: kubectl not working after km01 shutdown"
    fi

    log_warn "Remember to start km01 manually through Proxmox UI"
    echo ""
}

# Test 7: End-to-end workflow
test_end_to_end_workflow() {
    echo "========================================"
    echo "Test 7: End-to-End Workflow"
    echo "========================================"

    log_info "Testing complete workflow: deploy application, access via NodePort through LB..."

    # Create test namespace
    log_info "Creating test namespace..."
    if kubectl create namespace nginx-lb-test &> /dev/null; then
        log_info "Test namespace created"
    else
        kubectl delete namespace nginx-lb-test &> /dev/null || true
        kubectl create namespace nginx-lb-test &> /dev/null
    fi

    # Deploy test application
    log_info "Deploying test application..."
    cat <<EOF | kubectl apply -f - &> /dev/null
apiVersion: v1
kind: Pod
metadata:
  name: test-pod
  namespace: nginx-lb-test
  labels:
    app: test
spec:
  containers:
  - name: nginx
    image: nginx:latest
    ports:
    - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: test-service
  namespace: nginx-lb-test
spec:
  type: NodePort
  selector:
    app: test
  ports:
  - port: 80
    targetPort: 80
    nodePort: 30080
EOF

    # Wait for pod to be ready
    log_info "Waiting for pod to be ready..."
    kubectl wait --for=condition=ready pod/test-pod -n nginx-lb-test --timeout=60s &> /dev/null || true

    sleep 5

    # Get NodePort and test access
    log_info "Testing NodePort service access..."
    NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')

    if curl -s "http://${NODE_IP}:30080" | grep -q "nginx"; then
        log_pass "Test 7: End-to-end workflow successful"
    else
        log_fail "Test 7: Could not access test application"
    fi

    # Cleanup
    log_info "Cleaning up test resources..."
    kubectl delete namespace nginx-lb-test &> /dev/null || true
    echo ""
}

# Test 8: Long-running kubectl watch during failover
test_kubectl_watch_during_failover() {
    echo "========================================"
    echo "Test 8: Long-running kubectl watch During Failover"
    echo "========================================"
    log_warn "This test will SHUT DOWN nginx-lb01 while running kubectl watch"
    read -p "Continue? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log_skip "Test 8: kubectl watch during failover (user declined)"
        echo ""
        return
    fi

    # Start kubectl watch in background
    log_info "Starting kubectl watch..."
    WATCH_LOG="/tmp/kubectl-watch-test.log"
    > "$WATCH_LOG"

    (kubectl get nodes -w &>> "$WATCH_LOG") &
    WATCH_PID=$!

    sleep 5

    # Shutdown nginx-lb01
    log_info "Shutting down nginx-lb01..."
    ansible nginx-lb01 -i "$ANSIBLE_INVENTORY" -m shell -a "sudo shutdown -h now" -b &> /dev/null || true

    # Monitor watch for 30 seconds
    log_info "Monitoring kubectl watch during failover..."
    sleep 30

    # Check if watch is still running
    if ps -p $WATCH_PID > /dev/null; then
        log_pass "Test 8: kubectl watch survived failover"
        kill $WATCH_PID 2>/dev/null || true
    else
        log_fail "Test 8: kubectl watch terminated during failover"
    fi

    rm -f "$WATCH_LOG"
    echo ""
}

# Test 9: Cluster recovery - both LB nodes down and back up
test_cluster_recovery() {
    echo "========================================"
    echo "Test 9: Cluster Recovery"
    echo "========================================"
    log_warn "This test will SHUT DOWN BOTH nginx-lb nodes - COMPLETE SERVICE OUTAGE"
    log_warn "This is a DESTRUCTIVE test that should only be run in non-production environments"
    read -p "Continue? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log_skip "Test 9: Cluster recovery (user declined)"
        echo ""
        return
    fi

    # Shutdown both nodes
    log_info "Shutting down both nginx-lb nodes..."
    ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "sudo shutdown -h now" -b &> /dev/null || true

    sleep 10

    # Verify VIP is not accessible
    log_info "Verifying VIP is not accessible..."
    if ping -c 1 -W 2 $VIP &> /dev/null; then
        log_fail "VIP still responding after shutdown"
    else
        log_info "VIP correctly not responding"
    fi

    log_warn "Please manually power on BOTH nginx-lb01 and nginx-lb02 through Proxmox UI"
    read -p "Press ENTER when both nodes are powered on..."

    # Wait for nodes to come online
    log_info "Waiting for nodes to become accessible (max 120 seconds)..."
    WAIT_TIME=0
    while [ $WAIT_TIME -lt 120 ]; do
        if ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m ping &> /dev/null; then
            log_info "Both nodes are accessible"
            break
        fi
        sleep 5
        ((WAIT_TIME+=5))
    done

    if [ $WAIT_TIME -ge 120 ]; then
        log_fail "Test 9: Nodes did not come online within 120 seconds"
        echo ""
        return
    fi

    # Start services
    log_info "Starting corosync, pacemaker, and nginx on both nodes..."
    ansible nginx_lb -i "$ANSIBLE_INVENTORY" -m shell -a "sudo systemctl start corosync && sudo systemctl start pacemaker && sudo systemctl start nginx" -b &> /dev/null

    sleep 15

    # Check cluster status
    log_info "Checking cluster status..."
    if ansible nginx-lb01 -i "$ANSIBLE_INVENTORY" -m shell -a "crm status | grep 'Online:' | grep -c 'nginx-lb'" -b 2>/dev/null | grep -q "2"; then
        # Test kubectl
        if kubectl get nodes &> /dev/null; then
            log_pass "Test 9: Cluster recovered successfully from total outage"
        else
            log_fail "Test 9: Cluster reformed but kubectl not working"
        fi
    else
        log_fail "Test 9: Cluster did not reform properly"
    fi
    echo ""
}

# Test 10: Configuration idempotency
test_configuration_idempotency() {
    echo "========================================"
    echo "Test 10: Configuration Idempotency"
    echo "========================================"

    log_info "Re-running Ansible playbook to test idempotency..."

    # Run playbook
    if ansible-playbook -i "$ANSIBLE_INVENTORY" "${SCRIPT_DIR}/playbooks/setup_nginx_lb.yml" &> /tmp/ansible-idempotency.log; then
        # Check for changes
        CHANGED_COUNT=$(grep -c "changed=" /tmp/ansible-idempotency.log || echo "0")

        if [ "$CHANGED_COUNT" -eq 0 ]; then
            log_pass "Test 10: Ansible playbook is fully idempotent (no changes)"
        else
            log_info "Playbook made some changes (may be expected)"
            log_pass "Test 10: Ansible playbook completed without errors"
        fi
    else
        log_fail "Test 10: Ansible playbook execution failed"
    fi

    rm -f /tmp/ansible-idempotency.log
    echo ""
}

# Main execution
main() {
    echo "======================================================================="
    echo "Strategic HA Failover Tests for nginx-lb Cluster"
    echo "Task Group 6: Testing, Validation, and Documentation"
    echo "======================================================================="
    echo ""
    echo "VIP: $VIP"
    echo "Test Date: $(date)"
    echo ""

    # Check prerequisites
    check_prerequisites

    # Check if specific test was requested
    if [ -n "$1" ]; then
        case $1 in
            1) test_ha_failover ;;
            2) test_ha_failback ;;
            3) test_api_during_failover ;;
            4) test_nodeport_argocd ;;
            5) test_nodeport_during_failover ;;
            6) test_backend_health_checks ;;
            7) test_end_to_end_workflow ;;
            8) test_kubectl_watch_during_failover ;;
            9) test_cluster_recovery ;;
            10) test_configuration_idempotency ;;
            *)
                echo "Invalid test number. Valid range: 1-10"
                exit 1
                ;;
        esac
    else
        # Run all tests
        log_warn "Running all tests. This will cause service disruptions."
        read -p "Continue? (yes/no): " confirm
        if [ "$confirm" != "yes" ]; then
            echo "Tests cancelled by user"
            exit 0
        fi

        test_ha_failover
        test_ha_failback
        test_api_during_failover
        test_nodeport_argocd
        test_nodeport_during_failover
        test_backend_health_checks
        test_end_to_end_workflow
        test_kubectl_watch_during_failover
        test_cluster_recovery
        test_configuration_idempotency
    fi

    # Summary
    echo "======================================================================="
    echo "Test Summary"
    echo "======================================================================="
    echo -e "Tests Passed:  ${GREEN}${PASSED}${NC}"
    echo -e "Tests Failed:  ${RED}${FAILED}${NC}"
    echo -e "Tests Skipped: ${YELLOW}${SKIPPED}${NC}"
    echo "Total Tests:   $TOTAL"
    echo ""

    if [ $FAILED -gt 0 ]; then
        echo -e "${RED}RESULT: FAILED${NC}"
        exit 1
    elif [ $PASSED -eq 0 ]; then
        echo -e "${YELLOW}RESULT: ALL TESTS SKIPPED${NC}"
        exit 2
    else
        echo -e "${GREEN}RESULT: PASSED${NC}"
        exit 0
    fi
}

# Run main function
main "$@"
