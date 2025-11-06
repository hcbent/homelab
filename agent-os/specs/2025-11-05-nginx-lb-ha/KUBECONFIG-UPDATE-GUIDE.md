# Kubeconfig Update Guide for Load Balancer VIP

This guide provides instructions for updating kubeconfig files to use the nginx load balancer VIP endpoint instead of direct control plane node access.

## Overview

After deploying the nginx load balancer HA cluster, you need to update kubeconfig files to use the VIP endpoint:
- **Old endpoint**: `https://192.168.10.234:6443` (or km01/km02/km03)
- **New endpoint**: `https://192.168.10.250:6443` (VIP)

This ensures all kubectl operations go through the load balancer, providing high availability and automatic failover.

## Remote Cluster Nodes (Automated)

For Kubernetes cluster nodes (control plane and workers), use the Ansible playbook for automated updates.

### Prerequisites
- Task Group 4 completed (nginx LB operational)
- Ansible installed on your local machine
- SSH access to cluster nodes configured
- Cluster nodes accessible via inventory

### Quick Start

1. **Test in check mode first** (dry run):
   ```bash
   cd /Users/bret/git/homelab/ansible
   ansible-playbook -i inventory/lab playbooks/update_kubeconfig_remote_nodes.yml --check
   ```

2. **Update one control plane node first** (canary):
   ```bash
   ansible-playbook -i inventory/lab playbooks/update_kubeconfig_remote_nodes.yml --limit km01
   ```

3. **Verify it works**:
   ```bash
   ssh km01 'kubectl get nodes'
   ```

4. **Update remaining nodes**:
   ```bash
   ansible-playbook -i inventory/lab playbooks/update_kubeconfig_remote_nodes.yml
   ```

### What the Playbook Does

1. **Backup**: Creates timestamped backups of all kubeconfig files
2. **Update**: Changes server endpoint to VIP using regex replacement
3. **Validate**: Verifies kubeconfig syntax is still valid
4. **Test**: Runs `kubectl get nodes` to confirm connectivity
5. **Report**: Displays results for each host

### Rollback (if needed)

If something goes wrong, the playbook provides rollback commands. Example:

```bash
# SSH to the affected node
ssh km01

# Restore from backup (replace timestamp with actual value)
sudo cp /etc/kubernetes/admin.conf.backup.20251106T120000 /etc/kubernetes/admin.conf
cp ~/.kube/config.backup.20251106T120000 ~/.kube/config

# Verify restoration
kubectl get nodes
```

---

## Local Workstation (Manual)

For your MacBook or other workstations, use the manual procedure below.

### Prerequisites
- kubectl installed locally
- Existing kubeconfig file at `~/.kube/config`
- Network access to the VIP (192.168.10.250)

### Manual Update Procedure

#### Step 1: Backup your kubeconfig
```bash
# Create a timestamped backup
cp ~/.kube/config ~/.kube/config.backup.$(date +%Y%m%dT%H%M%S)

# Verify backup exists
ls -lh ~/.kube/config.backup.*
```

#### Step 2: Update the server endpoint

**Option A: Using sed (macOS/Linux)**
```bash
# Update the server endpoint to VIP
sed -i '' 's|server: https://[^:]*:6443|server: https://192.168.10.250:6443|' ~/.kube/config

# Note: On Linux, remove the '' after -i
# sed -i 's|server: https://[^:]*:6443|server: https://192.168.10.250:6443|' ~/.kube/config
```

**Option B: Using yq (if installed)**
```bash
# Install yq if needed: brew install yq

# Update the server endpoint
yq eval '.clusters[].cluster.server = "https://192.168.10.250:6443"' -i ~/.kube/config
```

**Option C: Manual editing**
```bash
# Open in your preferred editor
vim ~/.kube/config
# or
code ~/.kube/config

# Find the line that looks like:
#   server: https://192.168.10.234:6443
#
# Change it to:
#   server: https://192.168.10.250:6443
#
# Save and exit
```

#### Step 3: Verify the update
```bash
# Check the current server endpoint
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'
# Should output: https://192.168.10.250:6443

# Test connectivity
kubectl cluster-info

# Verify you can get nodes
kubectl get nodes

# Test a long-running command
kubectl get pods --all-namespaces
```

#### Step 4: Test certificate authentication
```bash
# Verify your authentication still works
kubectl auth whoami

# Or check your current context
kubectl config current-context

# Try a privileged operation
kubectl get namespaces
```

### Rollback (if needed)

If the update doesn't work or you encounter issues:

```bash
# Find your backup file
ls -lh ~/.kube/config.backup.*

# Restore from backup (use your actual backup filename)
cp ~/.kube/config.backup.20251106T120000 ~/.kube/config

# Verify restoration
kubectl get nodes
```

---

## Validation and Testing

After updating kubeconfig (remote or local), run these validation steps:

### Basic Connectivity
```bash
# 1. Verify server endpoint
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'
# Expected: https://192.168.10.250:6443

# 2. Test cluster info
kubectl cluster-info

# 3. Get nodes
kubectl get nodes

# 4. Get all pods
kubectl get pods --all-namespaces
```

### Certificate Authentication
```bash
# 5. Verify authentication
kubectl auth whoami

# 6. Test RBAC
kubectl auth can-i get pods --all-namespaces
```

### Long-Running Operations
```bash
# 7. Test watch operation (Ctrl+C to stop)
kubectl get pods --all-namespaces --watch

# 8. Test logs streaming (Ctrl+C to stop)
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=10 -f
```

### Load Balancer Behavior
```bash
# 9. Test failover resilience
# (In another terminal, stop nginx-lb01, kubectl should still work)

# 10. Verify no TLS errors
kubectl get nodes -v=6 2>&1 | grep -i "tls\|certificate"
# Should show successful TLS handshake, no errors
```

---

## Automated Testing

A comprehensive test script is available for validation:

```bash
# Run the test script
cd /Users/bret/git/homelab/ansible
./test-kubeconfig-lb.sh
```

This script runs 8 tests covering:
1. kubectl connection through VIP
2. kubectl get nodes
3. kubectl get pods --all-namespaces
4. Long-running kubectl commands
5. Server endpoint verification
6. Remote node operations
7. Backup file verification
8. Certificate authentication

---

## Troubleshooting

### Issue: "Unable to connect to the server"

**Symptoms**: kubectl commands fail with connection errors

**Solutions**:
1. Verify VIP is accessible:
   ```bash
   ping 192.168.10.250
   nc -zv 192.168.10.250 6443
   ```

2. Check nginx LB status:
   ```bash
   ssh nginx-lb01 'sudo systemctl status nginx'
   ssh nginx-lb01 'sudo crm status'
   ```

3. Verify VIP is assigned to one of the LB nodes:
   ```bash
   ssh nginx-lb01 'ip addr show | grep 192.168.10.250'
   ssh nginx-lb02 'ip addr show | grep 192.168.10.250'
   ```

### Issue: "x509: certificate signed by unknown authority"

**Symptoms**: TLS certificate validation errors

**Solutions**:
1. This should NOT happen (nginx is in passthrough mode)
2. Verify your kubeconfig has the correct certificate-authority-data
3. Check that you haven't modified the certificate fields in kubeconfig
4. Restore from backup if certificate data was accidentally changed

### Issue: kubectl works but some commands timeout

**Symptoms**: `kubectl get nodes` works, but `kubectl logs -f` times out

**Solutions**:
1. Check nginx timeout configuration:
   ```bash
   ssh nginx-lb01 'sudo nginx -T | grep timeout'
   ```

2. Verify proxy_timeout is set to 10m in nginx config

3. Check nginx error logs:
   ```bash
   ssh nginx-lb01 'sudo tail -f /var/log/nginx/error.log'
   ```

### Issue: "The connection to the server was refused"

**Symptoms**: kubectl commands fail immediately

**Solutions**:
1. Check if VIP is up:
   ```bash
   ssh nginx-lb01 'sudo crm resource status'
   ```

2. Verify nginx is running on the node with VIP:
   ```bash
   ssh nginx-lb01 'sudo systemctl status nginx'
   ```

3. Check if K8s API servers are accessible from LB:
   ```bash
   ssh nginx-lb01 'nc -zv 192.168.10.234 6443'
   ssh nginx-lb01 'nc -zv 192.168.10.235 6443'
   ssh nginx-lb01 'nc -zv 192.168.10.236 6443'
   ```

### Issue: kubectl works on some nodes but not others

**Symptoms**: kubectl works on km01 but fails on kube01

**Solutions**:
1. Check which nodes have been updated:
   ```bash
   ansible all -i inventory/lab -m shell -a "grep 'server:' /etc/kubernetes/admin.conf 2>/dev/null || echo 'No kubeconfig'"
   ```

2. Re-run the update playbook on specific node:
   ```bash
   ansible-playbook -i inventory/lab playbooks/update_kubeconfig_remote_nodes.yml --limit kube01
   ```

---

## Additional Information

### Network Topology

```
┌─────────────────────────────────────────────────┐
│ Your MacBook                                     │
│ ~/.kube/config -> https://192.168.10.250:6443   │
└────────────────────┬────────────────────────────┘
                     │
                     v
        ┌────────────────────────┐
        │   VIP: 192.168.10.250   │
        │   (Managed by Pacemaker)│
        └────────────┬───────────┘
                     │
        ┌────────────┴───────────┐
        │                        │
        v                        v
┌──────────────┐        ┌──────────────┐
│ nginx-lb01   │        │ nginx-lb02   │
│ 192.168.10.251│       │ 192.168.10.252│
│ (Primary)    │        │ (Standby)    │
└──────┬───────┘        └──────┬───────┘
       │                       │
       └───────────┬───────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
    v              v              v
┌─────────┐   ┌─────────┐   ┌─────────┐
│  km01   │   │  km02   │   │  km03   │
│ :6443   │   │ :6443   │   │ :6443   │
└─────────┘   └─────────┘   └─────────┘
Control Plane Nodes
```

### Why Update Kubeconfig?

**Benefits of using the load balancer:**
1. **High Availability**: If one control plane node fails, kubectl still works
2. **Automatic Failover**: If nginx-lb01 fails, VIP moves to nginx-lb02
3. **Load Distribution**: API requests distributed across all control plane nodes
4. **Single Endpoint**: One IP to manage instead of three
5. **Graceful Degradation**: System continues working even with node failures

**What doesn't change:**
- Certificate authentication (TLS passthrough maintains end-to-end encryption)
- RBAC permissions (authentication tokens unchanged)
- Cluster state (only access method changes)
- Application workloads (no impact on running pods)

### Monitoring the Load Balancer

Check load balancer health:

```bash
# Cluster status
ssh nginx-lb01 'sudo crm status'

# VIP location
ssh nginx-lb01 'sudo crm resource status'

# Nginx upstream status
ssh nginx-lb01 'sudo tail -f /var/log/nginx/access.log'

# Test direct VIP access
curl -k https://192.168.10.250:6443/healthz
```

---

## Summary Checklist

### For Remote Cluster Nodes:
- [ ] Task Group 4 completed (nginx LB operational)
- [ ] Run update playbook in check mode
- [ ] Update one control plane node (canary)
- [ ] Verify canary node works
- [ ] Update all remaining nodes
- [ ] Run validation tests
- [ ] Document any issues

### For Local Workstation:
- [ ] Create backup of ~/.kube/config
- [ ] Update server endpoint to VIP
- [ ] Verify kubectl connection
- [ ] Test basic operations
- [ ] Test long-running operations
- [ ] Confirm no certificate errors
- [ ] Run test script (optional)

### Post-Update Verification:
- [ ] All kubectl commands work through VIP
- [ ] Certificate authentication functional
- [ ] Watch operations work (kubectl get pods -w)
- [ ] Logs streaming works (kubectl logs -f)
- [ ] No TLS/certificate errors
- [ ] Backup files exist for rollback

---

## Support and References

- **Spec Document**: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/spec.md`
- **Tasks Document**: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/tasks.md`
- **Deployment Guide**: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/DEPLOYMENT-GUIDE.md`
- **Test Script**: `/Users/bret/git/homelab/ansible/test-kubeconfig-lb.sh`
- **Update Playbook (Remote)**: `/Users/bret/git/homelab/ansible/playbooks/update_kubeconfig_remote_nodes.yml`
- **Update Playbook (Local)**: `/Users/bret/git/homelab/ansible/playbooks/update_kubeconfig_for_lb.yml`

For issues or questions, refer to the troubleshooting section or review nginx/corosync logs on the load balancer nodes.
