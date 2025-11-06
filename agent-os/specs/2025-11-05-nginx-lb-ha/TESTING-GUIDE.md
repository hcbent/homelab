# Nginx Load Balancer HA - Testing Guide

This guide provides comprehensive instructions for testing the nginx load balancer HA cluster, including test execution, result interpretation, and troubleshooting.

## Overview

Testing is organized into 5 layers, with approximately 8-42 total tests:
1. Infrastructure Layer (2-8 tests) - Terraform validation
2. Inventory Configuration (2-8 tests) - Ansible inventory validation
3. Configuration Layer (2-8 tests) - Nginx and HA configuration
4. Integration Layer (2-8 tests) - Kubeconfig and kubectl functionality
5. Strategic Layer (10 tests) - End-to-end workflows and failover scenarios

## Test Scripts Location

All test scripts are located in the `/Users/bret/git/homelab/ansible/` directory:

```
ansible/
├── test-terraform.sh                    # Infrastructure layer tests (Task 2.1)
├── test-nginx-lb-inventory.sh           # Inventory configuration tests (Task 3.1)
├── test-nginx-ha-config.sh              # Configuration layer tests (Task 4.1)
├── test-kubeconfig-lb.sh                # Integration layer tests (Task 5.1)
└── test-strategic-ha-failover.sh        # Strategic tests (Task 6.2)
```

## Prerequisites

Before running tests, ensure:

1. **System Requirements:**
   - Ansible installed and configured
   - kubectl installed and configured
   - Terraform installed (for infrastructure tests)
   - SSH access to all nginx-lb nodes
   - Network connectivity to VIP (192.168.10.250)

2. **Deployment Status:**
   - VMs provisioned via Terraform
   - Ansible playbook executed successfully
   - HA cluster formed and operational
   - VIP accessible

3. **Permissions:**
   - SSH key authentication configured
   - Sudo access on nginx-lb nodes
   - Valid kubeconfig with cluster access

## Test Execution Order

### Phase 1: Pre-Deployment Testing (before terraform apply)

**Test 1: Infrastructure Layer (Terraform)**
```bash
cd /Users/bret/git/homelab/tf/nginx-lb
./test-terraform.sh
```

**Expected Results:**
- All 8 tests should PASS
- Configuration syntax valid
- Both VMs defined correctly
- IP addresses correct (251, 252)
- Anti-affinity configured
- VMIDs correct (250, 251)
- Storage backend is "tank"
- Tags correct

**If Tests Fail:**
- Review terraform.tfvars configuration
- Check main.tf for syntax errors
- Verify variables.tf definitions
- Re-run terraform validate

### Phase 2: Post-Provisioning Testing (after terraform apply)

**Test 2: Inventory Configuration**
```bash
cd /Users/bret/git/homelab/ansible
./test-nginx-lb-inventory.sh
```

**Expected Results:**
- Tests 1-4 should PASS (inventory structure)
- Tests 5-6 should PASS (connectivity - requires VMs provisioned)
- nginx_lb group contains both hosts
- ansible_host variables correct
- Group variables properly loaded
- Connectivity successful to both nodes

**If Tests Fail:**
- Verify VMs are powered on in Proxmox
- Check SSH key configuration
- Verify inventory file syntax
- Test manual SSH connection to nodes

### Phase 3: Post-Configuration Testing (after ansible playbook)

**Test 3: Configuration Layer**
```bash
cd /Users/bret/git/homelab/ansible
./test-nginx-ha-config.sh
```

**Expected Results:**
- All 8 tests should PASS
- Nginx running on both nodes
- Configuration syntax valid
- Stream and HTTP blocks configured
- Corosync running on both nodes
- Pacemaker running on both nodes
- VIP resource configured
- Cluster shows 2 nodes online

**If Tests Fail:**
- Review ansible playbook execution logs
- Check nginx error logs on nodes
- Verify corosync configuration
- Check cluster status with `crm status`

**Test 4: Integration Layer (Kubeconfig)**
```bash
cd /Users/bret/git/homelab/ansible
./test-kubeconfig-lb.sh
```

**Expected Results:**
- Tests using VIP endpoint should PASS
- kubectl connects through VIP
- kubectl get nodes works
- kubectl get pods works
- Long-running commands work
- Certificate authentication works

**If Tests Skip:**
- Some tests may skip if kubeconfig not yet updated
- Update kubeconfig using playbook
- Re-run tests after update

**If Tests Fail:**
- Verify VIP is accessible (ping 192.168.10.250)
- Check kubeconfig server endpoint
- Test direct connection to K8s API
- Review nginx stream configuration

### Phase 4: Strategic Testing (production readiness)

**Test 5: Strategic HA and Failover Tests**
```bash
cd /Users/bret/git/homelab/ansible
./test-strategic-ha-failover.sh
```

**IMPORTANT:** These tests are DESTRUCTIVE and will cause service disruptions. Only run during maintenance windows.

**Test Options:**
```bash
# Run all tests (requires confirmation)
./test-strategic-ha-failover.sh

# Run specific test
./test-strategic-ha-failover.sh 1   # HA failover
./test-strategic-ha-failover.sh 4   # NodePort accessibility (safe)
./test-strategic-ha-failover.sh 7   # End-to-end workflow (safe)
./test-strategic-ha-failover.sh 10  # Configuration idempotency (safe)
```

**Safe Tests (non-destructive):**
- Test 4: NodePort service accessibility
- Test 7: End-to-end workflow
- Test 10: Configuration idempotency

**Destructive Tests (require planning):**
- Test 1: HA failover (shuts down nginx-lb01)
- Test 2: HA failback (requires Test 1)
- Test 3: K8s API during failover (shuts down nginx-lb01)
- Test 5: NodePort during failover (shuts down nginx-lb01)
- Test 6: Backend health checks (shuts down km01)
- Test 8: kubectl watch during failover (shuts down nginx-lb01)
- Test 9: Cluster recovery (shuts down BOTH nodes)

## Test Execution Procedures

### Running Safe Tests First

**Step 1: Validate Infrastructure**
```bash
cd /Users/bret/git/homelab/tf/nginx-lb
./test-terraform.sh
echo "Exit code: $?"
```
**Expected:** Exit code 0, all tests pass

**Step 2: Validate Inventory**
```bash
cd /Users/bret/git/homelab/ansible
./test-nginx-lb-inventory.sh
echo "Exit code: $?"
```
**Expected:** Exit code 0, all tests pass

**Step 3: Validate Configuration**
```bash
cd /Users/bret/git/homelab/ansible
./test-nginx-ha-config.sh
echo "Exit code: $?"
```
**Expected:** Exit code 0, all tests pass

**Step 4: Validate Kubeconfig Integration**
```bash
cd /Users/bret/git/homelab/ansible
./test-kubeconfig-lb.sh
echo "Exit code: $?"
```
**Expected:** Exit code 0, most tests pass (some may skip)

**Step 5: Run Safe Strategic Tests**
```bash
cd /Users/bret/git/homelab/ansible

# Test NodePort accessibility
./test-strategic-ha-failover.sh 4
echo "Test 4 exit code: $?"

# Test end-to-end workflow
./test-strategic-ha-failover.sh 7
echo "Test 7 exit code: $?"

# Test configuration idempotency
./test-strategic-ha-failover.sh 10
echo "Test 10 exit code: $?"
```
**Expected:** All tests pass or skip gracefully

### Running Destructive Tests (Maintenance Window)

**IMPORTANT:** Schedule these tests during a maintenance window. Notify users that kubectl operations may be briefly interrupted.

**Pre-Test Checklist:**
- [ ] Maintenance window scheduled and communicated
- [ ] Backup of configurations created
- [ ] Monitoring alerts silenced (optional)
- [ ] Emergency contacts available
- [ ] Rollback plan prepared

**Test Sequence:**

**Test 1: HA Failover**
```bash
cd /Users/bret/git/homelab/ansible
./test-strategic-ha-failover.sh 1
```
**What Happens:**
- nginx-lb01 will be shut down
- VIP should move to nginx-lb02 within 30 seconds
- kubectl operations should continue with minimal disruption

**Post-Test:**
- nginx-lb01 will remain shut down
- Manually power on nginx-lb01 or proceed to Test 2

**Test 2: HA Failback**
```bash
# Power on nginx-lb01 in Proxmox UI first
./test-strategic-ha-failover.sh 2
```
**What Happens:**
- Script will wait for nginx-lb01 to come online
- Services will be started on nginx-lb01
- VIP should return to nginx-lb01 within 60 seconds

**Post-Test:**
- Both nodes should be online
- VIP should be on nginx-lb01

**Test 3: K8s API Availability During Failover**
```bash
./test-strategic-ha-failover.sh 3
```
**What Happens:**
- Continuous kubectl operations started in background
- nginx-lb01 shut down
- kubectl errors counted during failover
- Script analyzes results

**Expected:**
- Max 2-3 kubectl errors during failover window
- Most operations succeed

**Test 6: Backend Health Check Behavior**
```bash
./test-strategic-ha-failover.sh 6
```
**What Happens:**
- km01 (control plane node) will be shut down
- Nginx should detect failure and route to km02/km03
- kubectl should continue working

**Post-Test:**
- Remember to power on km01 in Proxmox UI

**Test 9: Cluster Recovery (MOST DESTRUCTIVE)**
```bash
./test-strategic-ha-failover.sh 9
```
**What Happens:**
- BOTH nginx-lb nodes shut down
- Complete service outage
- VIP not accessible
- kubectl operations will fail
- Script waits for manual node power-on
- Tests cluster reformation

**Post-Test:**
- Verify cluster reformed correctly
- Verify all services operational

## Interpreting Test Results

### Success Indicators

**Infrastructure Tests:**
```
[PASS] Test 1: Terraform validate
[PASS] Test 2: Both VMs defined in plan
...
All tests passed!
```

**Configuration Tests:**
```
[PASS] Test 1: Verify nginx installed and running on both nodes
[PASS] Test 2: Check nginx configuration syntax valid
...
Test Summary: 8 tests passed, 0 failed
```

**Strategic Tests:**
```
[PASS] Test 1: HA failover successful (15s) - kubectl still works
[PASS] Test 4: ArgoCD UI is accessible through load balancer
...
RESULT: PASSED
```

### Failure Indicators

**Infrastructure Test Failure:**
```
[FAIL] Test 3: Correct IP addresses
       Expected IPs 192.168.10.251 and 192.168.10.252
RESULT: FAILED
```
**Action:** Review terraform.tfvars and fix IP configuration

**Configuration Test Failure:**
```
[FAIL] Test 5: Verify corosync service running on both nodes
       Corosync service is not active
```
**Action:** Check corosync logs, restart service

**Strategic Test Failure:**
```
[FAIL] Test 1: VIP did not failover within 60 seconds
```
**Action:** Check corosync cluster status, review pacemaker logs

### Skipped Tests

Some tests may be skipped if prerequisites are not met:

```
[SKIP] Test 5: Connectivity test skipped (VMs not yet provisioned)
[INFO] This test requires VMs to be provisioned first
```
**Action:** Complete prerequisite steps and re-run tests

## Troubleshooting Test Failures

### Common Issues

**Issue 1: Terraform Tests Fail**
```
[FAIL] Test 1: Terraform configuration has syntax errors
```
**Diagnosis:**
```bash
cd /Users/bret/git/homelab/tf/nginx-lb
terraform validate
```
**Resolution:**
- Fix syntax errors in .tf files
- Re-run test

**Issue 2: Inventory Tests Fail - No Connectivity**
```
[FAIL] Test 5: Connectivity test failed
```
**Diagnosis:**
```bash
# Test manual SSH
ssh bret@192.168.10.251

# Test ansible ping
ansible nginx-lb01 -i ansible/inventory/lab -m ping
```
**Resolution:**
- Verify VMs are powered on
- Check network connectivity
- Verify SSH keys configured
- Check firewall rules

**Issue 3: Configuration Tests Fail - Services Not Running**
```
[FAIL] Test 1: Nginx service is not active
```
**Diagnosis:**
```bash
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo systemctl status nginx" -b
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo journalctl -u nginx -n 50" -b
```
**Resolution:**
- Check nginx error logs
- Test nginx configuration: `nginx -t`
- Restart nginx service
- Re-run ansible playbook

**Issue 4: Cluster Tests Fail - VIP Not Configured**
```
[FAIL] Test 7: cluster-vip resource not found
```
**Diagnosis:**
```bash
ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo crm status" -b
ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo crm configure show" -b
```
**Resolution:**
- Check pacemaker logs
- Verify corosync configuration
- Manually configure VIP if needed
- Re-run ansible playbook

**Issue 5: Kubeconfig Tests Fail - Wrong Endpoint**
```
[FAIL] Test 5: kubeconfig server endpoint is https://192.168.10.234:6443 (expected: https://192.168.10.250:6443)
```
**Diagnosis:**
```bash
kubectl config view --minify | grep server
```
**Resolution:**
```bash
cd /Users/bret/git/homelab/ansible
ansible-playbook -i inventory/lab playbooks/update_kubeconfig_for_lb.yml
```

**Issue 6: Strategic Tests Fail - Failover Too Slow**
```
[FAIL] Test 1: VIP did not failover within 60 seconds
```
**Diagnosis:**
```bash
# Check cluster status
ansible nginx-lb02 -i ansible/inventory/lab -m shell -a "sudo crm status" -b

# Check corosync logs
ansible nginx-lb02 -i ansible/inventory/lab -m shell -a "sudo journalctl -u corosync -n 100" -b
```
**Resolution:**
- Check corosync ring status
- Verify network connectivity between nodes
- Check pacemaker resource constraints
- Review corosync timeout settings

## Test Reporting

### Creating Test Report

After running all tests, create a comprehensive report:

**Report Template:**

```markdown
# Nginx Load Balancer HA - Test Results

**Test Date:** 2025-11-06
**Tested By:** [Your Name]
**Environment:** homelab

## Test Summary

| Test Layer | Tests Run | Passed | Failed | Skipped |
|------------|-----------|--------|--------|---------|
| Infrastructure (2.1) | 8 | 8 | 0 | 0 |
| Inventory (3.1) | 6 | 6 | 0 | 0 |
| Configuration (4.1) | 8 | 8 | 0 | 0 |
| Integration (5.1) | 8 | 7 | 0 | 1 |
| Strategic (6.2) | 10 | 9 | 0 | 1 |
| **TOTAL** | **40** | **38** | **0** | **2** |

## Infrastructure Tests (Test Group 2.1)

**Script:** test-terraform.sh
**Status:** PASS
**Duration:** 45 seconds

All infrastructure validation tests passed:
- Terraform syntax valid
- Both VMs properly defined
- IP addresses correct
- Anti-affinity configured
- VMIDs correct
- Storage and tags correct

## Inventory Tests (Test Group 3.1)

**Script:** test-nginx-lb-inventory.sh
**Status:** PASS
**Duration:** 30 seconds

All inventory tests passed:
- Inventory structure valid
- Both hosts in nginx_lb group
- Variables configured correctly
- Connectivity successful

## Configuration Tests (Test Group 4.1)

**Script:** test-nginx-ha-config.sh
**Status:** PASS
**Duration:** 2 minutes

All configuration tests passed:
- Nginx running on both nodes
- Configuration syntax valid
- Dual-purpose config deployed
- HA cluster formed correctly

## Integration Tests (Test Group 5.1)

**Script:** test-kubeconfig-lb.sh
**Status:** PASS (with 1 skip)
**Duration:** 1 minute

7 of 8 tests passed:
- kubectl works through VIP
- Certificate authentication working
- Test 7 skipped (no backup files found - expected)

## Strategic Tests (Test Group 6.2)

**Script:** test-strategic-ha-failover.sh
**Status:** PASS (with 1 skip)
**Duration:** 15 minutes

9 of 10 tests passed:
- HA failover successful (18 seconds)
- HA failback successful (22 seconds)
- NodePort services accessible
- End-to-end workflow successful
- Test 9 skipped (user declined total outage test)

### Failover Performance
- Failover time: 18 seconds
- Failback time: 22 seconds
- kubectl errors during failover: 1
- Service availability: 99.5% during test window

## Issues Found

None. All critical tests passed.

## Recommendations

1. Schedule Test 9 (cluster recovery) for next maintenance window
2. Create VM snapshots before major changes
3. Set up monitoring dashboards
4. Configure alert notifications

## Sign-Off

**Technical Lead:** _________________ Date: _______
**Operations Lead:** _________________ Date: _______

**Status:** APPROVED FOR PRODUCTION
```

## Automated Test Execution

For regular testing, create a master test script:

**File:** `/Users/bret/git/homelab/ansible/run-all-tests.sh`

```bash
#!/bin/bash
# Master test script - runs all test layers

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOG_DIR="${SCRIPT_DIR}/test-results"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Create log directory
mkdir -p "$LOG_DIR"

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo "======================================"
echo "Nginx LB HA - Comprehensive Test Suite"
echo "======================================"
echo "Start time: $(date)"
echo ""

# Test 1: Infrastructure (if in tf directory)
if [ -f "${SCRIPT_DIR}/../tf/nginx-lb/test-terraform.sh" ]; then
    echo "Running Infrastructure Tests..."
    cd "${SCRIPT_DIR}/../tf/nginx-lb"
    ./test-terraform.sh | tee "${LOG_DIR}/infrastructure-${TIMESTAMP}.log"
    INFRA_RESULT=$?
else
    echo "Skipping infrastructure tests (not in terraform directory)"
    INFRA_RESULT=2
fi

# Test 2: Inventory
echo ""
echo "Running Inventory Tests..."
cd "$SCRIPT_DIR"
./test-nginx-lb-inventory.sh | tee "${LOG_DIR}/inventory-${TIMESTAMP}.log"
INVENTORY_RESULT=$?

# Test 3: Configuration
echo ""
echo "Running Configuration Tests..."
./test-nginx-ha-config.sh | tee "${LOG_DIR}/configuration-${TIMESTAMP}.log"
CONFIG_RESULT=$?

# Test 4: Integration
echo ""
echo "Running Integration Tests..."
./test-kubeconfig-lb.sh | tee "${LOG_DIR}/integration-${TIMESTAMP}.log"
INTEGRATION_RESULT=$?

# Test 5: Strategic (safe tests only)
echo ""
echo "Running Strategic Tests (safe tests only)..."
./test-strategic-ha-failover.sh 4 | tee "${LOG_DIR}/strategic-test4-${TIMESTAMP}.log"
./test-strategic-ha-failover.sh 7 | tee "${LOG_DIR}/strategic-test7-${TIMESTAMP}.log"
./test-strategic-ha-failover.sh 10 | tee "${LOG_DIR}/strategic-test10-${TIMESTAMP}.log"

# Summary
echo ""
echo "======================================"
echo "Test Suite Complete"
echo "======================================"
echo "End time: $(date)"
echo ""
echo "Results:"
[ $INFRA_RESULT -eq 0 ] && echo -e "${GREEN}✓${NC} Infrastructure Tests" || echo -e "${RED}✗${NC} Infrastructure Tests"
[ $INVENTORY_RESULT -eq 0 ] && echo -e "${GREEN}✓${NC} Inventory Tests" || echo -e "${RED}✗${NC} Inventory Tests"
[ $CONFIG_RESULT -eq 0 ] && echo -e "${GREEN}✓${NC} Configuration Tests" || echo -e "${RED}✗${NC} Configuration Tests"
[ $INTEGRATION_RESULT -eq 0 ] && echo -e "${GREEN}✓${NC} Integration Tests" || echo -e "${RED}✗${NC} Integration Tests"
echo ""
echo "Logs saved to: ${LOG_DIR}"
echo ""

# Exit with failure if any critical test failed
if [ $INVENTORY_RESULT -ne 0 ] || [ $CONFIG_RESULT -ne 0 ] || [ $INTEGRATION_RESULT -ne 0 ]; then
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
else
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
fi
```

## Continuous Testing

**Schedule:** Run safe tests weekly via cron

```bash
# Add to crontab
0 2 * * 1 /Users/bret/git/homelab/ansible/run-all-tests.sh
```

## References

- Deployment Guide: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/DEPLOYMENT-GUIDE.md`
- Operational Procedures: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/OPERATIONAL-PROCEDURES.md`
- Validation Checklist: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/VALIDATION-CHECKLIST.md`

---

**Document Version:** 1.0
**Last Updated:** 2025-11-06
**Maintained By:** Infrastructure Team
