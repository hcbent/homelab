# Nginx Load Balancer HA - Deployment Guide

## Overview

This guide covers the deployment of a highly available nginx load balancer cluster for Kubernetes API and NodePort service access.

## Prerequisites

1. **Terraform Infrastructure Provisioned**: Both nginx-lb VMs must be running
   - Run: `cd /Users/bret/git/homelab/tf/nginx-lb && terraform apply -var-file=terraform.tfvars`
   - Verify: `terraform show`

2. **Ansible Inventory Configured**: nginx_lb group must be accessible
   - Test: `cd /Users/bret/git/homelab/ansible && ansible nginx_lb -i inventory/lab -m ping`

3. **Network Connectivity**: Both VMs must be reachable via SSH
   - nginx-lb01: 192.168.10.251
   - nginx-lb02: 192.168.10.252

## Deployment Steps

### Step 1: Run Playbook in Check Mode (Task 4.6)

First, validate what changes will be made without applying them:

```bash
cd /Users/bret/git/homelab/ansible
ansible-playbook playbooks/setup_nginx_lb.yml -i inventory/lab --check
```

**Expected Output:**
- Package installations (nginx, corosync, pacemaker, pcs, crmsh)
- Configuration file deployments
- Service starts and enables
- Cluster initialization tasks
- VIP resource creation

**Review:**
- No unexpected changes
- All templates render correctly
- No syntax errors

### Step 2: Execute Playbook on Primary Node (Task 4.7)

Deploy to nginx-lb01 first to establish the primary node:

```bash
cd /Users/bret/git/homelab/ansible
ansible-playbook playbooks/setup_nginx_lb.yml -i inventory/lab --limit nginx-lb01
```

**Verification on nginx-lb01:**
```bash
# Check nginx is running
ssh bret@192.168.10.251 "systemctl status nginx"

# Check nginx configuration
ssh bret@192.168.10.251 "sudo nginx -t"

# Check corosync is running
ssh bret@192.168.10.251 "sudo systemctl status corosync"

# Check cluster status (may show single node)
ssh bret@192.168.10.251 "sudo crm status"

# Check if VIP is initialized
ssh bret@192.168.10.251 "ip addr show | grep 192.168.10.250"
```

### Step 3: Execute Playbook on Secondary Node (Task 4.8)

Deploy to nginx-lb02 to complete the cluster:

```bash
cd /Users/bret/git/homelab/ansible
ansible-playbook playbooks/setup_nginx_lb.yml -i inventory/lab --limit nginx-lb02
```

**Verification on nginx-lb02:**
```bash
# Check nginx is running
ssh bret@192.168.10.252 "systemctl status nginx"

# Check nginx configuration
ssh bret@192.168.10.252 "sudo nginx -t"

# Check corosync is running
ssh bret@192.168.10.252 "sudo systemctl status corosync"

# Check node joined cluster
ssh bret@192.168.10.252 "sudo crm status"
```

### Step 4: Verify Cluster Status (Task 4.9)

Verify the complete cluster is operational:

```bash
# Check cluster status from both nodes
ssh bret@192.168.10.251 "sudo crm status"
ssh bret@192.168.10.252 "sudo crm status"
```

**Expected Cluster Status:**
```
Stack: corosync
Current DC: nginx-lb01 (version...)
Last updated: ...
Last change: ...

2 nodes configured
1 resource configured

Online: [ nginx-lb01 nginx-lb02 ]

Full list of resources:
  cluster-vip (ocf::heartbeat:IPaddr2): Started nginx-lb01

No resource failures
```

**Key Checks:**
- Both nodes show "Online"
- cluster-vip resource is "Started" on nginx-lb01 (preferred primary)
- No resource failures or errors
- VIP 192.168.10.250 is active

### Step 5: Run Configuration Tests (Task 4.10)

Execute the test suite to validate the deployment:

```bash
cd /Users/bret/git/homelab/ansible
./test-nginx-ha-config.sh
```

**Expected Results:**
- Test 1: PASS - Nginx running on both nodes
- Test 2: PASS - Nginx configuration valid
- Test 3: PASS - Stream block for K8s API exists
- Test 4: PASS - HTTP blocks for NodePort services exist
- Test 5: PASS - Corosync service running
- Test 6: PASS - Pacemaker service running
- Test 7: PASS - VIP resource configured
- Test 8: PASS - 2 nodes online

## Post-Deployment Validation

### Test VIP Accessibility

```bash
# Ping the VIP
ping -c 3 192.168.10.250

# Check which node has the VIP
ssh bret@192.168.10.251 "ip addr show | grep 192.168.10.250"
ssh bret@192.168.10.252 "ip addr show | grep 192.168.10.250"
```

### Test K8s API Access (Layer 4)

```bash
# Test TCP connection to K8s API through VIP
nc -zv 192.168.10.250 6443

# From a K8s node, update kubeconfig to use VIP (do this later in Task Group 5)
# kubectl --server=https://192.168.10.250:6443 get nodes
```

### Test NodePort Service Access (Layer 7)

```bash
# Test ArgoCD HTTP
curl -I http://192.168.10.250:8080

# Test Traefik HTTP
curl -I http://192.168.10.250:80

# Note: These will only work once services are actually deployed on K8s
```

### Test Health Check Endpoint

```bash
# Check nginx health endpoint
curl http://192.168.10.250:8888/health
# Expected: "healthy"
```

## Troubleshooting

### Nginx Issues

```bash
# Check nginx error log
ssh bret@192.168.10.251 "sudo tail -f /var/log/nginx/error.log"

# Test configuration
ssh bret@192.168.10.251 "sudo nginx -t"

# Reload configuration
ssh bret@192.168.10.251 "sudo systemctl reload nginx"
```

### Corosync Issues

```bash
# Check corosync log
ssh bret@192.168.10.251 "sudo tail -f /var/log/corosync/corosync.log"

# Check corosync-cfgtool
ssh bret@192.168.10.251 "sudo corosync-cfgtool -s"

# Restart corosync
ssh bret@192.168.10.251 "sudo systemctl restart corosync"
```

### Pacemaker Issues

```bash
# Check pacemaker status
ssh bret@192.168.10.251 "sudo pcs status"

# View cluster configuration
ssh bret@192.168.10.251 "sudo crm configure show"

# Clear resource failures
ssh bret@192.168.10.251 "sudo crm resource cleanup cluster-vip"
```

### VIP Not Active

```bash
# Check resource status
ssh bret@192.168.10.251 "sudo crm resource status cluster-vip"

# Force VIP to start
ssh bret@192.168.10.251 "sudo crm resource start cluster-vip"

# Check for resource failures
ssh bret@192.168.10.251 "sudo crm status"
```

## Configuration Files

### Key Files Deployed

1. **Nginx Configuration**: `/etc/nginx/conf.d/k8s-loadbalancer.conf`
   - Stream block for K8s API (port 6443)
   - HTTP blocks for NodePort services
   - Health check endpoint (port 8888)

2. **Corosync Configuration**: `/etc/corosync/corosync.conf`
   - Two-node cluster settings
   - Quorum configuration
   - Node definitions

3. **Corosync Auth Key**: `/etc/corosync/authkey`
   - Cluster authentication key
   - Must be identical on both nodes

## Important Notes

### VM Provisioning Dependency

- Tasks 4.6-4.10 require VMs to be provisioned first
- Run `terraform apply` before executing these playbook tasks
- Test connectivity with `ansible nginx_lb -m ping` before proceeding

### Idempotency

The playbook is designed to be idempotent:
- Can be re-run safely without causing issues
- Uses conditional checks for cluster resources
- Only creates resources if they don't exist

### Automatic Failback

The cluster is configured with nginx-lb01 as the preferred primary:
- VIP will automatically return to nginx-lb01 when it recovers
- Location constraint: `prefer-nginx-lb01 cluster-vip 50: nginx-lb01`
- Resource stickiness: 100 (prevents unnecessary failovers)

## Next Steps

After successful deployment:

1. **Task Group 5**: Update kubeconfig files to use VIP endpoint
2. **Task Group 6**: Comprehensive testing and validation
3. **Monitoring**: Integrate with Prometheus/Grafana
4. **Documentation**: Update operational procedures

## Acceptance Criteria Checklist

- [ ] Both nginx-lb VMs provisioned and accessible
- [ ] Nginx installed and running on both nodes
- [ ] Dual-purpose configuration deployed (stream + http blocks)
- [ ] Corosync cluster formed with 2 nodes
- [ ] Pacemaker managing VIP resource
- [ ] VIP (192.168.10.250) accessible and responds to ping
- [ ] nginx-lb01 is preferred primary node
- [ ] All 8 configuration tests pass
