# Nginx Load Balancer Testing Guide

This document describes the testing strategy for the Nginx Load Balancer HA cluster deployment.

## Test Scripts Overview

### 1. Inventory Configuration Tests (`test-nginx-lb-inventory.sh`)
**Purpose:** Validate Ansible inventory structure and configuration
**Run When:** After creating/updating inventory files
**Dependencies:** None (runs locally)

**Tests Performed:**
1. Validate inventory file syntax
2. Verify nginx_lb group contains both hosts
3. Check ansible_host variables are correct (251, 252)
4. Validate group variables exist (cluster_vip, cluster_name)
5. Test connectivity to both hosts (skipped if VMs not provisioned)
6. Verify sudo access (skipped if VMs not provisioned)

**Usage:**
```bash
./test-nginx-lb-inventory.sh
```

**Expected Results:**
- Tests 1-4: PASS (inventory structure tests)
- Tests 5-6: SKIP (until VMs are provisioned)

---

### 2. Connectivity Tests (`test-nginx-lb-connectivity.sh`)
**Purpose:** Test network connectivity and SSH access to nginx LB nodes
**Run When:** After VMs are provisioned via Terraform
**Dependencies:** VMs must be running and SSH accessible

**Tests Performed:**
1. Ansible ping to both hosts
2. Test individual node connectivity
3. Verify sudo access on both nodes
4. Check SSH key authentication
5. Gather basic system facts
6. Check disk space on both nodes

**Usage:**
```bash
./test-nginx-lb-connectivity.sh
```

**Expected Results:**
- All 6 tests should PASS
- If tests fail, see troubleshooting section

---

## Test Execution Workflow

### Phase 1: Inventory Configuration (Task Group 3)
**Status:** Can be tested immediately

```bash
# Run inventory tests
./test-nginx-lb-inventory.sh
```

**Expected Outcome:**
- 4 tests pass (inventory structure)
- 2 tests skipped (connectivity - VMs not yet provisioned)

---

### Phase 2: After Terraform Apply (Task Group 2)
**Status:** Run after `terraform apply` completes in tf/nginx-lb/

```bash
# First, verify VMs are running in Proxmox
# Check IPs: 192.168.10.251 and 192.168.10.252

# Run connectivity tests
./test-nginx-lb-connectivity.sh

# Re-run inventory tests (should now pass all 6 tests)
./test-nginx-lb-inventory.sh
```

**Expected Outcome:**
- All connectivity tests pass
- SSH key authentication working
- Sudo access confirmed

---

### Phase 3: After Nginx/Corosync Deployment (Task Group 4)
**Status:** Run after ansible playbook execution

Additional tests will be added in Task Group 4 to verify:
- Nginx installed and running
- Corosync cluster formed
- Pacemaker managing VIP
- Dual-purpose nginx configuration (stream + HTTP)

---

## Troubleshooting

### Inventory Tests Fail
**Symptom:** Tests 1-4 fail with syntax errors

**Solutions:**
1. Check `/Users/bret/git/homelab/ansible/inventory/lab` syntax
2. Verify YAML syntax in `/Users/bret/git/homelab/ansible/group_vars/nginx_lb.yml`
3. Run: `ansible-inventory -i inventory/lab --list` to see detailed errors

### Connectivity Tests Fail
**Symptom:** Tests 1-6 fail with connection errors

**Solutions:**
1. Verify VMs are running in Proxmox:
   - nginx-lb01 (192.168.10.251, VMID 250)
   - nginx-lb02 (192.168.10.252, VMID 251)

2. Test basic network connectivity:
   ```bash
   ping 192.168.10.251
   ping 192.168.10.252
   ```

3. Check SSH access manually:
   ```bash
   ssh bret@192.168.10.251
   ssh bret@192.168.10.252
   ```

4. Verify cloud-init deployed SSH keys:
   ```bash
   ssh bret@192.168.10.251 "cat ~/.ssh/authorized_keys"
   ```

5. Check cloud-init logs on VMs:
   ```bash
   ssh bret@192.168.10.251 "sudo cat /var/log/cloud-init.log"
   ```

6. Verify ansible.cfg and SSH key configuration:
   ```bash
   cat /Users/bret/git/homelab/ansible/ansible.cfg
   ```

### SSH Key Authentication Fails
**Symptom:** Password prompts appear during ansible commands

**Solutions:**
1. Verify SSH key exists: `ls -la /Users/bret/.ssh/github_rsa`
2. Check ansible.cfg private_key_file setting
3. Verify cloud-init injected the correct public key
4. Test SSH manually with key:
   ```bash
   ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.251
   ```

### Sudo Access Fails
**Symptom:** "sudo: a password is required" errors

**Solutions:**
1. Verify cloud-init configured passwordless sudo
2. Check /etc/sudoers.d/ on VMs
3. Verify ansible_user is correct in inventory (should be 'bret')

---

## Test Results Documentation

### Task Group 3 Completion Status

**Test 3.1-3.4: Inventory Configuration**
- Date Tested: 2025-11-06
- Result: ✅ PASS (4/4 tests)
- Notes: All inventory structure tests pass

**Test 3.5-3.6: Connectivity Tests**
- Status: ⏳ PENDING (requires VM provisioning)
- Dependencies: Task Group 2 terraform apply
- Test Scripts: Created and ready
- Notes: Run after terraform apply completes

---

## Next Steps

After all tests pass:

1. **Task Group 4:** Deploy nginx and corosync configuration
   - Run: `ansible-playbook playbooks/setup_nginx_lb.yml`
   - Verify dual-purpose nginx config (API + NodePort)
   - Confirm corosync cluster formed

2. **Task Group 5:** Update kubeconfig files
   - Update remote cluster nodes to use VIP
   - Test kubectl operations through load balancer

3. **Task Group 6:** Comprehensive HA testing
   - Test VIP failover behavior
   - Validate NodePort service accessibility
   - Confirm automatic failback to primary

---

## Test Scripts Location

All test scripts are located in: `/Users/bret/git/homelab/ansible/`

- `test-nginx-lb-inventory.sh` - Inventory structure tests
- `test-nginx-lb-connectivity.sh` - Network connectivity tests
- Additional scripts will be created in Task Groups 4-6

---

## References

- Spec: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/spec.md`
- Tasks: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/tasks.md`
- Infrastructure Summary: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/planning/infrastructure-resolution-summary.md`
