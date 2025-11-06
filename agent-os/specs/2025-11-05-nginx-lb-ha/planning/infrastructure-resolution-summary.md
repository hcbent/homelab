# Infrastructure Planning Resolution Summary

**Date:** 2025-11-06
**Task Group:** 1 - Infrastructure Planning & IP Resolution
**Status:** COMPLETE

## Executive Summary

Task Group 1 has been completed successfully. All critical infrastructure questions have been resolved through codebase analysis of existing Terraform configurations, Ansible inventories, and Kubespray deployment files. This document provides a comprehensive summary of all resolved questions and the final architecture decisions.

## Key Findings

### Critical Discovery: Actual Cluster Architecture

The most important discovery was identifying the **actual deployed Kubernetes cluster architecture** which differs from the original spec assumptions:

**Spec Assumptions (Incorrect):**
- Control plane: kube01-03 at 192.168.10.11-13
- Workers: kube04-06 at 192.168.10.14-16

**Actual Deployed Architecture (Correct):**
- Control plane: **km01-03** at 192.168.10.234-236
- Workers: **kube01-03** at 192.168.10.237-239

### Evidence Sources

1. **Kubespray Inventory**: `/Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini`
   - Authoritative source showing km01-03 as control plane nodes
   - Shows kube01-03 as worker nodes
   - Documents actual IP addresses used in production

2. **Terraform Configurations**: `/Users/bret/git/homelab/tf/kubernetes/terraform.tfvars`
   - Shows planned IPs (11-13) that were never deployed
   - Confirms pattern of 3 Proxmox hosts (pve1, pve2, pve3)

3. **Existing Nginx Playbook**: `/Users/bret/git/homelab/ansible/playbooks/setup_nginx_lb.yml`
   - Shows 237-239 IPs for NodePort backends
   - Confirms NodePort service configurations

## Resolved Infrastructure Questions

### OQ-1: Proxmox Host Placement

**Decision:** Split across different Proxmox hosts for true hypervisor-level HA

**Configuration:**
- **nginx-lb01**: Deploy to **pve1** (192.168.10.251, VMID 250)
- **nginx-lb02**: Deploy to **pve2** (192.168.10.252, VMID 251)

**Rationale:**
- Provides true hypervisor-level HA
- Survives single Proxmox host failure
- Follows existing pattern used for Kubernetes nodes

### OQ-2: Corosync Quorum Policy

**Decision:** Use `two_node: 1` quorum policy

**Rationale:**
- Standard approach for 2-node clusters
- Allows cluster to operate when one node fails
- Proven track record in homelab environments

**Configuration Location:** Will be set in `corosync.conf.j2` template

### OQ-3: STONITH Configuration

**Decision:** Disable STONITH (`stonith-enabled=false`)

**Rationale:**
- Acceptable for homelab environment with controlled conditions
- Reduces implementation complexity
- two_node quorum + health checks provide sufficient protection

**Configuration Location:** Will be set in pacemaker cluster properties

### OQ-4: Control Plane Node IPs (CRITICAL)

**Resolution:**

**Control Plane Nodes** (for K8s API load balancing on port 6443):
| Node | IP Address | Location | Specs |
|------|------------|----------|-------|
| km01 | 192.168.10.234 | Bare metal | 4 cores, 16GB RAM |
| km02 | 192.168.10.235 | VM on pve1 | 4 cores, 8GB RAM |
| km03 | 192.168.10.236 | VM on pve2 | 4 cores, 8GB RAM |

**Impact:** Nginx stream block will target **km01-03** at **234-236** for K8s API

### OQ-5: Worker Node IPs (CRITICAL)

**Resolution:**

**Worker Nodes** (for NodePort service load balancing):
| Node | IP Address | Location | Specs |
|------|------------|----------|-------|
| kube01 | 192.168.10.237 | VM on pve3 | 8 cores, 16GB RAM |
| kube02 | 192.168.10.238 | VM on pve1 | 8 cores, 16GB RAM |
| kube03 | 192.168.10.239 | VM on pve2 | 8 cores, 16GB RAM |

**Impact:** Nginx HTTP block will target **kube01-03** at **237-239** for NodePort services

**Important Note:** There is NO kube04-06 in the deployment (6-node total, not 9-node)

### OQ-6: Initial NodePort Services

**Decision:** Start with four services, design for extensibility

**Initial Services:**
| Service | Listen Port | NodePort | Description |
|---------|-------------|----------|-------------|
| ArgoCD HTTP | 8080 | 31160 | ArgoCD UI (HTTP) |
| ArgoCD HTTPS | 8443 | 32442 | ArgoCD UI (HTTPS) |
| Traefik HTTP | 80 | 31469 | Traefik Ingress (HTTP) |
| Traefik HTTPS | 443 | 31685 | Traefik Ingress (HTTPS) |

**Extensibility:** Design allows adding services via Ansible `services` array variable

### OQ-7: Log Retention

**Decision:** Use default Ubuntu logrotate configuration

**Configuration:**
- Daily rotation
- Keep 14 days
- Can be adjusted post-deployment based on actual log volume

### OQ-8: Backup Strategy

**Decision:** Infrastructure as Code provides implicit backup

**Approach:**
- Nginx config: Git (Jinja2 template)
- Corosync config: Git (Jinja2 template)
- Recovery: Re-run Ansible playbook
- VIP state: Transient, managed by corosync

## Additional Research Resolutions

### AR-1: Corosync Network Configuration

**Decision:**
- Transport: UDP unicast (UDPU) for 2-node cluster
- Token timeout: Default 1000ms
- Network: Single interface acceptable (same subnet)

### AR-2: Nginx Performance Tuning

**Decision:**
- Initial timeouts: `proxy_timeout=10m`, `proxy_connect_timeout=10s`
- Monitor post-deployment
- Adjust via Ansible playbook re-run if needed

### AR-3: VM Anti-Affinity

**Decision:**
- Method: Manual `target_node` assignment in terraform.tfvars
- Verification: Review terraform plan before apply
- Rationale: Proxmox provider doesn't support anti-affinity rules

### AR-4: Fence Agents

**Decision:**
- STONITH disabled, fence agent research not needed
- Can revisit if split-brain issues occur

## Final Architecture

### Load Balancer Cluster

```
nginx-lb01 (192.168.10.251, pve1, VMID 250)
    |
    +-- Virtual IP: 192.168.10.250 (corosync managed)
    |
nginx-lb02 (192.168.10.252, pve2, VMID 251)

HA: Corosync with two_node quorum, STONITH disabled
Failover: Automatic, preferred primary: nginx-lb01
```

### Kubernetes Control Plane (API Server Backends)

```
Nginx Stream Block (Port 6443 TCP Passthrough)
    |
    +-- km01: 192.168.10.234 (bare metal)
    +-- km02: 192.168.10.235 (VM on pve1)
    +-- km03: 192.168.10.236 (VM on pve2)

Load Balancing: least_conn
Health Checks: max_fails=2, fail_timeout=30s
Timeouts: proxy_timeout=10m, proxy_connect_timeout=10s
```

### Kubernetes Worker Nodes (NodePort Backends)

```
Nginx HTTP Block (NodePort Services)
    |
    +-- kube01: 192.168.10.237 (VM on pve3)
    +-- kube02: 192.168.10.238 (VM on pve1)
    +-- kube03: 192.168.10.239 (VM on pve2)

Load Balancing: least_conn
Health Checks: max_fails=2, fail_timeout=30s
WebSocket: Supported with HTTP/1.1 upgrade headers
```

### Network Architecture

```
                 Internet/Local Network
                          |
                          v
              +-----------------------+
              |  Virtual IP (VIP)     |
              |  192.168.10.250       |
              +-----------------------+
                     |        |
        +------------+        +------------+
        |                                  |
        v                                  v
+----------------+                +----------------+
| nginx-lb01     |   Corosync    | nginx-lb02     |
| 192.168.10.251 | <-----------> | 192.168.10.252 |
| (pve1)         |   Heartbeat   | (pve2)         |
+----------------+                +----------------+
        |                                  |
        +----------------------------------+
                          |
        +-----------------+-----------------+
        |                                   |
        v                                   v
+-------------------+           +-------------------+
| K8s API (6443)    |           | NodePort Services |
|                   |           |                   |
| km01: .234        |           | kube01: .237      |
| km02: .235        |           | kube02: .238      |
| km03: .236        |           | kube03: .239      |
+-------------------+           +-------------------+
```

## Configuration Impact Summary

### Terraform Configuration
- Create two VMs with anti-affinity (pve1, pve2)
- VMID 250 and 251
- Static IPs: 251 and 252
- VIP variable: 250

### Ansible Configuration
- Inventory group: `[nginx_lb]` with both nodes
- Group vars: `cluster_vip`, `cluster_name`, `k8s_control_plane`, `k8s_workers`
- Control plane targets: km01-03 at 234-236
- Worker targets: kube01-03 at 237-239

### Nginx Configuration
- **Stream block**: Port 6443 to km01-03 (234-236)
- **HTTP block**: NodePort services to kube01-03 (237-239)
- Separate upstreams for control plane vs workers

## Acceptance Criteria Status

All acceptance criteria for Task Group 1 have been met:

- [x] All control plane and worker node IPs confirmed and documented
- [x] Proxmox host placement strategy finalized
- [x] Corosync configuration parameters decided
- [x] Open questions document updated with resolutions

## Next Steps

With Task Group 1 complete, the project is ready to proceed to:

1. **Task Group 2**: Terraform Infrastructure Layer
   - Update terraform.tfvars with two-node configuration
   - Set anti-affinity via target_node assignment
   - Provision nginx-lb01 on pve1, nginx-lb02 on pve2

2. **Task Group 3**: Ansible Inventory Configuration
   - Create `[nginx_lb]` inventory group
   - Define group_vars with confirmed IPs

3. **Task Group 4**: Nginx and Corosync Configuration
   - Deploy dual-purpose nginx config (stream + HTTP)
   - Establish corosync cluster with resolved parameters

## Documentation Updates

The following documents have been updated with resolution details:

1. **`planning/open-questions.md`**
   - All OQ-1 through OQ-8 marked as RESOLVED
   - All AR-1 through AR-4 marked as RESOLVED or DEFERRED
   - Resolution tracking table updated
   - Architecture summary section added

2. **`tasks.md`**
   - Task 1.0 through 1.5 marked as complete [x]
   - Ready for Task Group 2 implementation

## References

### Source Files Analyzed
- `/Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini`
- `/Users/bret/git/homelab/tf/kubernetes/terraform.tfvars`
- `/Users/bret/git/homelab/tf/nginx-lb/terraform.tfvars`
- `/Users/bret/git/homelab/ansible/playbooks/setup_nginx_lb.yml`
- `/Users/bret/git/homelab/ansible/inventory/lab`

### Key Discoveries
1. Cluster uses km01-03 (not kube01-03) for control plane
2. Only 6 nodes total (3 control, 3 worker), not 9
3. IP range 234-239 (not 11-16 as originally assumed)
4. Three Proxmox hosts available (pve1, pve2, pve3)
5. Existing nginx playbook provides NodePort service definitions

### Implementation Notes
- Ensure nginx configuration distinguishes between control plane and workers
- Use correct node names: km01-03 for API, kube01-03 for NodePort
- Verify terraform plan shows anti-affinity before apply
- Test corosync cluster formation on both nodes
- Validate VIP assignment and failover behavior

---

**Task Group 1 Status: COMPLETE**
**Ready for Task Group 2: Yes**
**Blocking Issues: None**
