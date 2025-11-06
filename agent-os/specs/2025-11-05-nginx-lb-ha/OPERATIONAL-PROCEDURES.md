# Nginx Load Balancer HA - Operational Procedures

This document provides comprehensive operational procedures for the nginx load balancer HA cluster.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Daily Operations](#daily-operations)
- [Monitoring and Health Checks](#monitoring-and-health-checks)
- [Troubleshooting](#troubleshooting)
- [Maintenance Procedures](#maintenance-procedures)
- [Disaster Recovery](#disaster-recovery)
- [Common Commands](#common-commands)
- [Alerts and Notifications](#alerts-and-notifications)

## Architecture Overview

### Cluster Components

**HA Cluster:**
- **nginx-lb01** (192.168.10.251) - Primary node on pve1
- **nginx-lb02** (192.168.10.252) - Secondary node on pve2
- **VIP** (192.168.10.250) - Shared cluster IP managed by Pacemaker

**Load Balancing Services:**
1. **Kubernetes API Server** (Layer 4 TCP passthrough)
   - Port: 6443
   - Backend: Control plane nodes (km01-03) at 192.168.10.234-236
   - Algorithm: least_conn
   - Health checks: max_fails=2, fail_timeout=30s

2. **NodePort Services** (Layer 7 HTTP/HTTPS proxy)
   - ArgoCD: Ports 8080/8443 -> NodePorts 31160/32442
   - Traefik: Ports 80/443 -> NodePorts 31469/31685
   - Backend: Worker nodes (kube01-03) at 192.168.10.237-239
   - Algorithm: least_conn
   - Health checks: max_fails=2, fail_timeout=30s

**HA Stack:**
- **Corosync:** Cluster communication and membership management
- **Pacemaker:** Resource management and VIP failover
- **Configuration:** Two-node cluster with automatic failback to nginx-lb01

### Failover Behavior

**Normal Operation:**
- VIP active on nginx-lb01 (preferred primary)
- Both nodes have identical nginx configuration
- Traffic flows through VIP to active node

**Failover Scenario:**
- Primary node (nginx-lb01) fails or stops
- Corosync detects failure (typically < 10 seconds)
- Pacemaker moves VIP to nginx-lb02
- Total failover time: < 30 seconds
- No manual intervention required

**Failback Scenario:**
- nginx-lb01 comes back online
- Pacemaker automatically returns VIP to nginx-lb01 (preferred primary)
- Failback time: typically 15-30 seconds

## Daily Operations

### Checking Cluster Status

```bash
# Check cluster status from either node
ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo crm status" -b

# Check which node has VIP
ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo crm resource status cluster-vip" -b

# Check both nodes are online
ansible nginx_lb -i ansible/inventory/lab -m ping
```

### Verifying Service Health

```bash
# Check nginx is running on both nodes
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo systemctl status nginx" -b

# Check corosync is running
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo systemctl status corosync" -b

# Check pacemaker is running
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo systemctl status pacemaker" -b

# Test VIP accessibility
ping -c 3 192.168.10.250

# Test K8s API through load balancer
kubectl --server=https://192.168.10.250:6443 get nodes

# Test NodePort service (ArgoCD)
curl -I http://192.168.10.250:8080
```

### Viewing Logs

```bash
# Nginx access logs
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo tail -f /var/log/nginx/access.log" -b

# Nginx error logs
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo tail -f /var/log/nginx/error.log" -b

# Corosync logs
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo journalctl -u corosync -f" -b

# Pacemaker logs
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo journalctl -u pacemaker -f" -b
```

## Monitoring and Health Checks

### Key Metrics to Monitor

**Cluster Health:**
- Cluster node status (both nodes should be Online)
- VIP location and status
- Corosync ring status
- Pacemaker resource status

**Load Balancer Health:**
- Nginx service status
- Backend connection counts
- Failed backend count (max_fails threshold)
- Request rate and error rate
- Response time percentiles

**Backend Health:**
- Control plane node availability (K8s API)
- Worker node availability (NodePort services)
- Node response times

### Manual Health Checks

```bash
# Comprehensive health check script
cd /Users/bret/git/homelab/ansible
./test-nginx-ha-config.sh

# Test kubeconfig integration
./test-kubeconfig-lb.sh

# Run strategic HA tests (individual tests)
./test-strategic-ha-failover.sh 4  # Test NodePort accessibility
./test-strategic-ha-failover.sh 7  # Test end-to-end workflow
./test-strategic-ha-failover.sh 10 # Test configuration idempotency
```

### Health Check Endpoints

**Nginx Health Endpoint:**
- URL: http://192.168.10.250:8888/health
- Expected Response: 200 OK with "OK" message
- Use for external monitoring systems

**Example Prometheus Query:**
```promql
# Nginx up status
up{job="nginx-lb"}

# Backend health
nginx_upstream_status{upstream=~"k8s_api_servers|argocd_backend|traefik_backend"}
```

## Troubleshooting

### VIP Not Responding

**Symptoms:**
- Cannot ping 192.168.10.250
- kubectl commands fail with connection refused

**Diagnosis:**
```bash
# Check cluster status
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo crm status" -b

# Check VIP resource
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo crm resource status cluster-vip" -b

# Check corosync membership
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo corosync-cmapctl | grep members" -b
```

**Resolution:**
1. Verify both nodes are online in cluster
2. Check VIP resource is started
3. If VIP is stopped, start it manually:
   ```bash
   ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo crm resource start cluster-vip" -b
   ```
4. If cluster is split-brain, restart corosync on both nodes:
   ```bash
   ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo systemctl restart corosync pacemaker" -b
   ```

### Nginx Configuration Errors

**Symptoms:**
- Nginx fails to start or reload
- 502 Bad Gateway errors
- Backend connections failing

**Diagnosis:**
```bash
# Test nginx configuration syntax
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo nginx -t" -b

# Check nginx error logs
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo tail -100 /var/log/nginx/error.log" -b

# Check backend connectivity
ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "curl -k https://192.168.10.234:6443" -b
```

**Resolution:**
1. Fix configuration syntax errors
2. Verify backend IPs are correct
3. Reload nginx configuration:
   ```bash
   ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo systemctl reload nginx" -b
   ```
4. If reload fails, restart nginx:
   ```bash
   ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo systemctl restart nginx" -b
   ```

### Cluster Split-Brain

**Symptoms:**
- Both nodes think they are primary
- VIP responds on both nodes (IP conflict)
- Cluster status shows inconsistent state

**Diagnosis:**
```bash
# Check cluster status from both nodes
ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo crm status" -b
ansible nginx-lb02 -i ansible/inventory/lab -m shell -a "sudo crm status" -b

# Check corosync ring status
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo corosync-cfgtool -s" -b
```

**Resolution:**
1. Stop pacemaker on both nodes:
   ```bash
   ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo systemctl stop pacemaker" -b
   ```
2. Stop corosync on both nodes:
   ```bash
   ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo systemctl stop corosync" -b
   ```
3. Start corosync on primary first:
   ```bash
   ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo systemctl start corosync" -b
   sleep 5
   ```
4. Start pacemaker on primary:
   ```bash
   ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo systemctl start pacemaker" -b
   sleep 10
   ```
5. Start corosync on secondary:
   ```bash
   ansible nginx-lb02 -i ansible/inventory/lab -m shell -a "sudo systemctl start corosync" -b
   sleep 5
   ```
6. Start pacemaker on secondary:
   ```bash
   ansible nginx-lb02 -i ansible/inventory/lab -m shell -a "sudo systemctl start pacemaker" -b
   ```

### Backend Node Failures

**Symptoms:**
- Some kubectl operations fail intermittently
- NodePort services return 502 errors
- Nginx logs show "upstream timed out"

**Diagnosis:**
```bash
# Check all backend nodes are accessible
ansible km01,km02,km03 -i ansible/inventory/lab -m ping
ansible kube01,kube02,kube03 -i ansible/inventory/lab -m ping

# Test K8s API on each control plane node
for node in 234 235 236; do
  curl -k https://192.168.10.$node:6443
done

# Check nginx upstream status
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo grep -A10 'k8s_api_servers' /var/log/nginx/error.log" -b
```

**Resolution:**
1. Identify failed backend node(s)
2. Verify node is running in Proxmox
3. Check node network connectivity
4. Restart node if necessary
5. Nginx will automatically resume using the node after fail_timeout (30s)

### kubectl Commands Failing

**Symptoms:**
- kubectl commands hang or timeout
- Connection refused errors
- Certificate validation errors

**Diagnosis:**
```bash
# Check current kubeconfig server
kubectl config view --minify | grep server

# Test direct connection to VIP
curl -k https://192.168.10.250:6443

# Test direct connection to control plane node
curl -k https://192.168.10.234:6443

# Check nginx stream configuration
ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo nginx -T | grep -A20 'stream {'" -b
```

**Resolution:**
1. Verify kubeconfig is using VIP endpoint (https://192.168.10.250:6443)
2. Update kubeconfig if needed:
   ```bash
   cd ansible
   ansible-playbook -i inventory/lab playbooks/update_kubeconfig_for_lb.yml
   ```
3. Test kubectl connectivity:
   ```bash
   kubectl cluster-info
   kubectl get nodes
   ```

## Maintenance Procedures

### Planned Maintenance on Primary Node (nginx-lb01)

**Procedure:**
1. Verify cluster is healthy:
   ```bash
   ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo crm status" -b
   ```
2. Verify VIP is on nginx-lb01:
   ```bash
   ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo crm resource status cluster-vip" -b
   ```
3. Move VIP to secondary (optional, for minimal disruption):
   ```bash
   ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo crm resource move cluster-vip nginx-lb02" -b
   ```
4. Wait for VIP to move (typically 5-10 seconds)
5. Verify kubectl still works through VIP
6. Perform maintenance on nginx-lb01
7. Return VIP to primary:
   ```bash
   ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo crm resource unmove cluster-vip" -b
   ```

### Planned Maintenance on Secondary Node (nginx-lb02)

**Procedure:**
1. Verify VIP is on nginx-lb01 (primary):
   ```bash
   ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo crm resource status cluster-vip" -b
   ```
2. If VIP is on nginx-lb02, move it to primary:
   ```bash
   ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo crm resource move cluster-vip nginx-lb01" -b
   ```
3. Wait for VIP to move
4. Perform maintenance on nginx-lb02
5. Verify node rejoins cluster after maintenance:
   ```bash
   ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo crm status" -b
   ```

### Updating Nginx Configuration

**Procedure:**
1. Update configuration in Git repository:
   - Edit `ansible/templates/nginx-lb.conf.j2`
   - Edit `ansible/group_vars/nginx_lb.yml` (if needed)
2. Commit changes to Git
3. Test configuration update on secondary first:
   ```bash
   cd ansible
   ansible-playbook -i inventory/lab playbooks/setup_nginx_lb.yml --limit nginx-lb02 --check
   ```
4. Apply configuration to secondary:
   ```bash
   ansible-playbook -i inventory/lab playbooks/setup_nginx_lb.yml --limit nginx-lb02
   ```
5. Verify nginx reloaded successfully on secondary
6. Test configuration update on primary:
   ```bash
   ansible-playbook -i inventory/lab playbooks/setup_nginx_lb.yml --limit nginx-lb01 --check
   ```
7. Apply configuration to primary:
   ```bash
   ansible-playbook -i inventory/lab playbooks/setup_nginx_lb.yml --limit nginx-lb01
   ```
8. Verify both nodes have identical configuration:
   ```bash
   ansible nginx_lb -i inventory/lab -m shell -a "sudo md5sum /etc/nginx/conf.d/load-balancer.conf" -b
   ```

### Adding New NodePort Service

**Procedure:**
1. Identify NodePort service details:
   - Service name
   - NodePort number
   - Listen port on load balancer
2. Update `ansible/group_vars/nginx_lb.yml`:
   ```yaml
   services:
     - name: argocd-http
       listen_port: 8080
       node_port: 31160
       protocol: http
     - name: argocd-https
       listen_port: 8443
       node_port: 32442
       protocol: https
     - name: new-service    # Add new service
       listen_port: 9000
       node_port: 30900
       protocol: http
   ```
3. Follow "Updating Nginx Configuration" procedure above
4. Test new service accessibility:
   ```bash
   curl http://192.168.10.250:9000
   ```

### Updating Backend Node IPs

**Procedure:**
1. Update `ansible/group_vars/nginx_lb.yml`:
   ```yaml
   k8s_control_plane:
     - name: km01
       ip: 192.168.10.234
     - name: km02
       ip: 192.168.10.235
     - name: km03
       ip: 192.168.10.236

   k8s_workers:
     - name: kube01
       ip: 192.168.10.237
     - name: kube02
       ip: 192.168.10.238
     - name: kube03
       ip: 192.168.10.239
   ```
2. Follow "Updating Nginx Configuration" procedure above
3. Verify backend connectivity:
   ```bash
   ansible nginx_lb -i inventory/lab -m shell -a "sudo nginx -t" -b
   ```

## Disaster Recovery

### Total Cluster Failure (Both Nodes Down)

**Recovery Procedure:**
1. Power on both nodes through Proxmox UI
2. Wait for nodes to boot (typically 1-2 minutes)
3. Verify SSH access:
   ```bash
   ansible nginx_lb -i ansible/inventory/lab -m ping
   ```
4. Start corosync on primary first:
   ```bash
   ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo systemctl start corosync" -b
   sleep 5
   ```
5. Start pacemaker on primary:
   ```bash
   ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo systemctl start pacemaker" -b
   sleep 10
   ```
6. Start corosync on secondary:
   ```bash
   ansible nginx-lb02 -i ansible/inventory/lab -m shell -a "sudo systemctl start corosync" -b
   sleep 5
   ```
7. Start pacemaker on secondary:
   ```bash
   ansible nginx-lb02 -i ansible/inventory/lab -m shell -a "sudo systemctl start pacemaker" -b
   sleep 10
   ```
8. Verify cluster reformed:
   ```bash
   ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo crm status" -b
   ```
9. Start nginx on both nodes (if not already running):
   ```bash
   ansible nginx_lb -i ansible/inventory/lab -m shell -a "sudo systemctl start nginx" -b
   ```
10. Verify kubectl works through VIP:
    ```bash
    kubectl get nodes
    ```

### Corrupted Nginx Configuration

**Recovery Procedure:**
1. Restore configuration from Git:
   ```bash
   cd ansible
   ansible-playbook -i inventory/lab playbooks/setup_nginx_lb.yml
   ```
2. If playbook fails, restore from backup:
   ```bash
   ansible nginx_lb -i inventory/lab -m shell -a "sudo cp /etc/nginx/conf.d/load-balancer.conf.backup /etc/nginx/conf.d/load-balancer.conf" -b
   ```
3. Test configuration:
   ```bash
   ansible nginx_lb -i inventory/lab -m shell -a "sudo nginx -t" -b
   ```
4. Reload nginx:
   ```bash
   ansible nginx_lb -i inventory/lab -m shell -a "sudo systemctl reload nginx" -b
   ```

### Corrupted Corosync/Pacemaker Configuration

**Recovery Procedure:**
1. Stop services on both nodes:
   ```bash
   ansible nginx_lb -i inventory/lab -m shell -a "sudo systemctl stop pacemaker corosync" -b
   ```
2. Restore configuration from Git:
   ```bash
   cd ansible
   ansible-playbook -i inventory/lab playbooks/setup_nginx_lb.yml --tags corosync
   ```
3. Start corosync on primary:
   ```bash
   ansible nginx-lb01 -i inventory/lab -m shell -a "sudo systemctl start corosync" -b
   sleep 5
   ```
4. Start pacemaker on primary:
   ```bash
   ansible nginx-lb01 -i inventory/lab -m shell -a "sudo systemctl start pacemaker" -b
   sleep 10
   ```
5. Start services on secondary:
   ```bash
   ansible nginx-lb02 -i inventory/lab -m shell -a "sudo systemctl start corosync pacemaker" -b
   ```
6. Reconfigure VIP resource:
   ```bash
   ansible nginx-lb01 -i inventory/lab -m shell -a "sudo crm configure primitive cluster-vip IPaddr2 params ip=192.168.10.250 cidr_netmask=24 op monitor interval=10s" -b
   ansible nginx-lb01 -i inventory/lab -m shell -a "sudo crm configure location prefer-nginx-lb01 cluster-vip 100: nginx-lb01" -b
   ```

### VM Snapshot Rollback

**When to Use:**
- Catastrophic configuration corruption
- Suspected system compromise
- Failed upgrade with no clear recovery path

**Procedure:**
1. Identify snapshot to restore in Proxmox UI
2. Stop pacemaker on the node to be restored:
   ```bash
   ansible nginx-lb01 -i ansible/inventory/lab -m shell -a "sudo systemctl stop pacemaker corosync" -b
   ```
3. Rollback snapshot in Proxmox UI
4. Start node and wait for boot
5. Follow "Total Cluster Failure" recovery procedure

## Common Commands

### Cluster Management

```bash
# View cluster status
sudo crm status

# View detailed cluster configuration
sudo crm configure show

# View VIP resource status
sudo crm resource status cluster-vip

# Manually move VIP to another node
sudo crm resource move cluster-vip <node-name>

# Remove move constraint (allow automatic failback)
sudo crm resource unmove cluster-vip

# Stop VIP resource
sudo crm resource stop cluster-vip

# Start VIP resource
sudo crm resource start cluster-vip

# View corosync ring status
sudo corosync-cfgtool -s

# View corosync membership
sudo corosync-cmapctl | grep members

# View pacemaker constraints
sudo crm configure show | grep location
```

### Nginx Management

```bash
# Test nginx configuration
sudo nginx -t

# Reload nginx (graceful, no downtime)
sudo systemctl reload nginx

# Restart nginx (brief interruption)
sudo systemctl restart nginx

# View nginx version and modules
sudo nginx -V

# View full nginx configuration (including included files)
sudo nginx -T

# Check nginx process and connections
sudo ss -tlnp | grep nginx

# View active connections
sudo netstat -an | grep :6443 | wc -l
sudo netstat -an | grep :8080 | wc -l
```

### Log Analysis

```bash
# View recent nginx access logs
sudo tail -100 /var/log/nginx/access.log

# View nginx error logs
sudo tail -100 /var/log/nginx/error.log

# Count requests by status code
sudo awk '{print $9}' /var/log/nginx/access.log | sort | uniq -c | sort -rn

# View corosync logs
sudo journalctl -u corosync -n 100

# View pacemaker logs
sudo journalctl -u pacemaker -n 100

# Follow all cluster logs in real-time
sudo journalctl -u corosync -u pacemaker -f
```

### Testing and Validation

```bash
# Test VIP connectivity
ping -c 3 192.168.10.250

# Test K8s API through VIP
curl -k https://192.168.10.250:6443

# Test kubectl through VIP
kubectl --server=https://192.168.10.250:6443 get nodes

# Test NodePort service
curl http://192.168.10.250:8080

# Run comprehensive health checks
cd /Users/bret/git/homelab/ansible
./test-nginx-ha-config.sh
./test-kubeconfig-lb.sh

# Run specific strategic test
./test-strategic-ha-failover.sh 4  # NodePort accessibility
```

## Alerts and Notifications

### Critical Alerts

Set up monitoring alerts for the following critical conditions:

1. **VIP Not Responding**
   - Alert: VIP (192.168.10.250) not responding to ping
   - Severity: Critical
   - Action: Immediate investigation required

2. **Cluster Split-Brain**
   - Alert: Both nodes claim to be primary
   - Severity: Critical
   - Action: Follow split-brain recovery procedure

3. **Both Nodes Down**
   - Alert: Neither nginx-lb node responding
   - Severity: Critical
   - Action: Follow total cluster failure recovery

4. **Failover Event**
   - Alert: VIP moved to secondary node
   - Severity: Warning
   - Action: Investigate why primary failed

### Warning Alerts

1. **Single Node Down**
   - Alert: One nginx-lb node not accessible
   - Severity: Warning
   - Action: Investigate within 1 hour

2. **Backend Node Down**
   - Alert: One or more K8s nodes not reachable
   - Severity: Warning
   - Action: Investigate backend node health

3. **High Error Rate**
   - Alert: Nginx 5xx errors > 5% of requests
   - Severity: Warning
   - Action: Check backend health and nginx logs

4. **Configuration Drift**
   - Alert: Nginx configuration differs between nodes
   - Severity: Warning
   - Action: Re-run Ansible playbook

### Monitoring Integration

**Prometheus Metrics to Export:**
- nginx_up (1 = running, 0 = down)
- nginx_connections_active
- nginx_connections_waiting
- nginx_http_requests_total
- nginx_upstream_status
- corosync_cluster_members
- pacemaker_resources_status

**Example Prometheus AlertManager Rules:**
```yaml
groups:
  - name: nginx-lb-ha
    rules:
      - alert: NginxLBDown
        expr: up{job="nginx-lb"} == 0
        for: 1m
        annotations:
          summary: "Nginx LB node {{ $labels.instance }} is down"

      - alert: VIPNotResponding
        expr: probe_success{target="192.168.10.250"} == 0
        for: 1m
        annotations:
          summary: "VIP 192.168.10.250 is not responding"

      - alert: ClusterFailover
        expr: pacemaker_resource_location{resource="cluster-vip"} != on(instance) nginx-lb01
        for: 5m
        annotations:
          summary: "VIP has failed over to secondary node"
```

## References

- [Nginx Stream Module Documentation](http://nginx.org/en/docs/stream/ngx_stream_core_module.html)
- [Corosync Configuration Guide](https://clusterlabs.org/pacemaker/doc/en-US/Pacemaker/2.0/html/Clusters_from_Scratch/)
- [Pacemaker Resource Management](https://clusterlabs.org/pacemaker/doc/)
- Deployment Guide: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/DEPLOYMENT-GUIDE.md`
- Kubeconfig Update Guide: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/KUBECONFIG-UPDATE-GUIDE.md`

---

**Document Version:** 1.0
**Last Updated:** 2025-11-06
**Maintained By:** Infrastructure Team
