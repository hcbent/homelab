# Task Group 5: Deployment Notes

## Overview

Task Group 5 (Kubeconfig Update and Validation) configuration is **COMPLETE** and ready for deployment.

All playbooks, test scripts, and documentation have been created. However, actual execution of tasks 5.3-5.8 requires:

1. **VMs to be provisioned** (Task Group 2 - terraform apply)
2. **Nginx LB cluster operational** (Task Group 4 - ansible playbook execution)

## Implementation Status

### COMPLETE - Configuration Tasks

✅ **Task 5.1**: Test scripts written
- File: `/Users/bret/git/homelab/ansible/test-kubeconfig-lb.sh`
- 8 focused tests covering all kubeconfig functionality
- Ready to execute after VMs are provisioned

✅ **Task 5.2**: Ansible playbooks created
- Remote nodes playbook: `/Users/bret/git/homelab/ansible/playbooks/update_kubeconfig_remote_nodes.yml`
- Local workstation playbook: `/Users/bret/git/homelab/ansible/playbooks/update_kubeconfig_for_lb.yml`
- Comprehensive error handling and rollback procedures included

✅ **Task 5.6**: Documentation created
- Guide: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/KUBECONFIG-UPDATE-GUIDE.md`
- Covers both automated (remote nodes) and manual (local workstation) procedures
- Includes troubleshooting, validation, and rollback instructions

### PENDING - Execution Tasks (Requires VM Provisioning)

⏳ **Task 5.3**: Test playbook in check mode
- Command ready: `ansible-playbook -i inventory/lab playbooks/update_kubeconfig_remote_nodes.yml --check`
- Requires: VMs provisioned, SSH access configured

⏳ **Task 5.4**: Execute on one control plane node
- Command ready: `ansible-playbook -i inventory/lab playbooks/update_kubeconfig_remote_nodes.yml --limit km01`
- Requires: Task 4 complete (nginx LB operational)

⏳ **Task 5.5**: Execute on remaining nodes
- Command ready: `ansible-playbook -i inventory/lab playbooks/update_kubeconfig_remote_nodes.yml`
- Requires: Task 5.4 successful

⏳ **Task 5.7**: Test kubectl operations
- Validation commands documented in KUBECONFIG-UPDATE-GUIDE.md
- Requires: kubeconfig updates applied

⏳ **Task 5.8**: Run functionality tests
- Command ready: `/Users/bret/git/homelab/ansible/test-kubeconfig-lb.sh`
- Requires: kubeconfig updates applied

## Prerequisites for Execution

### 1. Infrastructure Ready (Task Group 2)
```bash
# Navigate to terraform directory
cd /Users/bret/git/homelab/tf/nginx-lb

# Provision VMs
terraform apply -var-file=terraform.tfvars

# Verify VMs are accessible
ssh bret@192.168.10.251  # nginx-lb01
ssh bret@192.168.10.252  # nginx-lb02
```

### 2. Nginx LB Operational (Task Group 4)
```bash
# Navigate to ansible directory
cd /Users/bret/git/homelab/ansible

# Deploy nginx and corosync/pacemaker
ansible-playbook -i inventory/lab playbooks/setup_nginx_lb.yml

# Verify cluster status
ssh nginx-lb01 'sudo crm status'

# Verify VIP is assigned
ping 192.168.10.250
```

## Deployment Sequence (When Ready)

Once prerequisites are met, execute tasks in this order:

### Step 1: Check Mode (Task 5.3)
```bash
cd /Users/bret/git/homelab/ansible

# Dry run - see what would change
ansible-playbook -i inventory/lab playbooks/update_kubeconfig_remote_nodes.yml --check
```

**Expected Output:**
- Shows which kubeconfig files would be backed up
- Shows which files would be updated
- No actual changes made

### Step 2: Canary Deployment (Task 5.4)
```bash
# Update one control plane node first
ansible-playbook -i inventory/lab playbooks/update_kubeconfig_remote_nodes.yml --limit km01

# Verify it works
ssh km01 'kubectl get nodes'
```

**Success Criteria:**
- Backup files created on km01
- Server endpoint updated to https://192.168.10.250:6443
- kubectl commands work through VIP
- No errors or warnings

### Step 3: Full Deployment (Task 5.5)
```bash
# Update all remaining nodes
ansible-playbook -i inventory/lab playbooks/update_kubeconfig_remote_nodes.yml

# Or update specific groups
ansible-playbook -i inventory/lab playbooks/update_kubeconfig_remote_nodes.yml --limit km02,km03
ansible-playbook -i inventory/lab playbooks/update_kubeconfig_remote_nodes.yml --limit kube01,kube02,kube03
```

**Success Criteria:**
- All nodes updated successfully
- All backup files created
- kubectl works on all nodes
- Cluster operations stable

### Step 4: Local Workstation Update
```bash
# Follow manual procedure in KUBECONFIG-UPDATE-GUIDE.md

# Quick version:
cp ~/.kube/config ~/.kube/config.backup.$(date +%Y%m%dT%H%M%S)
sed -i '' 's|server: https://[^:]*:6443|server: https://192.168.10.250:6443|' ~/.kube/config
kubectl get nodes
```

### Step 5: Validation Testing (Task 5.7)
```bash
# Basic connectivity
kubectl cluster-info
kubectl get nodes
kubectl get pods --all-namespaces

# Long-running operations
kubectl get pods --all-namespaces --watch  # Ctrl+C to stop

# Find a running pod for logs test
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=10 -f  # Ctrl+C to stop

# Certificate authentication
kubectl auth whoami
```

### Step 6: Automated Testing (Task 5.8)
```bash
cd /Users/bret/git/homelab/ansible

# Run comprehensive test suite
./test-kubeconfig-lb.sh
```

**Expected Results:**
- 8 tests total
- All tests PASS (or reasonable SKIPs with explanations)
- No test FAILURES

## Rollback Procedures

### If Update Fails on Remote Node

SSH to the affected node and restore from backup:

```bash
# SSH to node
ssh km01  # or whichever node failed

# Find backup file
ls -lh /etc/kubernetes/admin.conf.backup.*
ls -lh ~/.kube/config.backup.*

# Restore (replace timestamp with actual value)
sudo cp /etc/kubernetes/admin.conf.backup.TIMESTAMP /etc/kubernetes/admin.conf
cp ~/.kube/config.backup.TIMESTAMP ~/.kube/config

# Verify
kubectl get nodes
```

### If Update Fails on Local Workstation

```bash
# Find backup
ls -lh ~/.kube/config.backup.*

# Restore
cp ~/.kube/config.backup.TIMESTAMP ~/.kube/config

# Verify
kubectl get nodes
```

## Success Metrics

Task Group 5 is considered complete when:

- ✅ All 8 tests in test-kubeconfig-lb.sh pass
- ✅ Kubeconfig updated on all remote cluster nodes
- ✅ Backup files created before all modifications
- ✅ kubectl commands work through VIP (192.168.10.250:6443)
- ✅ Documentation exists for local kubeconfig updates
- ✅ No certificate validation errors
- ✅ Watch and long-running operations function correctly

## Files Created

### Test Scripts
- `/Users/bret/git/homelab/ansible/test-kubeconfig-lb.sh` - 8 focused tests

### Ansible Playbooks
- `/Users/bret/git/homelab/ansible/playbooks/update_kubeconfig_remote_nodes.yml` - Remote node updates
- `/Users/bret/git/homelab/ansible/playbooks/update_kubeconfig_for_lb.yml` - Local workstation updates

### Documentation
- `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/KUBECONFIG-UPDATE-GUIDE.md` - Comprehensive guide
- `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/TASK-5-DEPLOYMENT-NOTES.md` - This file

## Next Steps

1. **Complete Task Group 2**: Run `terraform apply` to provision nginx-lb VMs
2. **Complete Task Group 4**: Run nginx LB playbook to deploy cluster
3. **Execute Task Group 5**: Follow deployment sequence above
4. **Proceed to Task Group 6**: Comprehensive testing and validation

## Notes

- All configuration tasks (5.1, 5.2, 5.6) are marked as complete
- Execution tasks (5.3-5.8) are marked as pending with clear dependencies
- All files are ready for immediate use when prerequisites are met
- Comprehensive error handling and rollback procedures are in place
- Documentation covers both automated and manual update procedures
