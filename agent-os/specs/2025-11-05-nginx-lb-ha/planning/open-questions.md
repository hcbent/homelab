# Open Questions and Additional Research

This document tracks open questions, areas requiring additional research, and decisions deferred for implementation phase.

## Open Questions

### OQ-1: Proxmox Target Node Assignment

**Question:** Which Proxmox host(s) should nginx-lb01 and nginx-lb02 be deployed to?

**Context:**
- Need to determine if both VMs should be on same Proxmox host or spread across multiple hosts
- Current cluster has multiple Proxmox nodes (based on target_node references in other configs)

**Options:**
1. Both on same Proxmox host (simpler, but creates single point of failure at hypervisor level)
2. Split across different Proxmox hosts (better HA, survives hypervisor failure)

**Recommendation:** Split across different Proxmox hosts for true HA

**STATUS: RESOLVED**

**Resolution:**
- **nginx-lb01**: Deploy to **pve1** (192.168.10.251, VMID 250)
- **nginx-lb02**: Deploy to **pve2** (192.168.10.252, VMID 251)
- **Rationale**: Distributing across different Proxmox hosts provides true hypervisor-level HA. The homelab infrastructure has three Proxmox nodes (pve1, pve2, pve3) as confirmed by terraform configurations.
- **Evidence**: All existing multi-node deployments (Kubernetes control plane, worker nodes) are distributed across pve1, pve2, and pve3.

**Needs Resolution:** No - Resolved

**Impact:** Medium - affects true HA capability

---

### OQ-2: Corosync Quorum Policy

**Question:** What quorum policy should be used for 2-node corosync cluster?

**Context:**
- Two-node clusters have inherent split-brain risk
- Need to decide on quorum policy: two_node=1, wait_for_all, or auto_tie_breaker

**Options:**
1. `two_node: 1` - Traditional two-node policy (allows operation with single node)
2. `wait_for_all: 1` - Requires both nodes to be up (prevents split-brain but reduces availability)
3. `auto_tie_breaker: 1` - Uses lowest node ID as tie-breaker (modern approach)

**Recommendation:** Use `two_node: 1` for simplicity and proven track record

**STATUS: RESOLVED**

**Resolution:**
- **Decision**: Use `two_node: 1` quorum policy
- **Rationale**: This is the standard approach for 2-node clusters in homelab environments. It allows the cluster to continue operating when one node fails, which is the primary purpose of the HA configuration.
- **Configuration**: Will be set in corosync.conf.j2 template in the quorum section

**Needs Resolution:** No - Resolved

**Impact:** Medium - affects failover behavior and split-brain handling

---

### OQ-3: STONITH Configuration

**Question:** Should STONITH (Shoot The Other Node In The Head) be enabled for the cluster?

**Context:**
- STONITH prevents split-brain by forcibly powering off failed nodes
- Requires fence agent for Proxmox or other fencing mechanism
- Homelab environment may not need this level of protection

**Options:**
1. Enable STONITH with Proxmox fence agent (most robust, more complex)
2. Disable STONITH (simpler, accept minimal split-brain risk)

**Recommendation:** Disable STONITH for homelab (accept low risk, reduce complexity)

**STATUS: RESOLVED**

**Resolution:**
- **Decision**: Disable STONITH (set `stonith-enabled=false` in pacemaker configuration)
- **Rationale**: For a homelab environment with controlled conditions and minimal risk, the added complexity of STONITH is not justified. The two_node quorum policy combined with proper health checking is sufficient.
- **Configuration**: Will be disabled in pacemaker cluster properties during cluster initialization

**Needs Resolution:** No - Resolved

**Impact:** Low - homelab can tolerate occasional split-brain recovery

---

### OQ-4: Exact Control Plane Node IPs

**Question:** What are the exact IP addresses for kube01, kube02, kube03?

**Context:**
- Need precise IP addresses for nginx upstream configuration
- User mentioned km01, km02, km03 in answer but likely meant kube01, kube02, kube03
- Based on pattern, likely 192.168.10.11-13 but needs confirmation

**Assumption:** Based on existing infrastructure pattern:
- kube01: 192.168.10.11 (or 237?)
- kube02: 192.168.10.12 (or 238?)
- kube03: 192.168.10.13 (or 239?)

**Note:** Existing playbook shows different IPs (237-239) - needs clarification

**STATUS: RESOLVED**

**Resolution:**
Based on analysis of kubespray inventory (`kubespray/inventory/homelab/hosts.ini`) and terraform configurations, the actual cluster architecture is:

**CONTROL PLANE NODES** (for K8s API load balancing on port 6443):
- **km01**: 192.168.10.234 (bare metal, 4 cores, 16GB RAM)
- **km02**: 192.168.10.235 (VM on pve1, 4 cores, 8GB RAM)
- **km03**: 192.168.10.236 (VM on pve2, 4 cores, 8GB RAM)

**WORKER NODES** (for NodePort service load balancing):
- **kube01**: 192.168.10.237 (VM on pve3, 8 cores, 16GB RAM)
- **kube02**: 192.168.10.238 (VM on pve1, 8 cores, 16GB RAM)
- **kube03**: 192.168.10.239 (VM on pve2, 8 cores, 16GB RAM)

**Key Clarification:**
- The existing nginx playbook was incorrectly labeling worker nodes as "kube01-03" when defining backend for NodePort services
- The actual Kubernetes cluster deployed via Kubespray uses:
  - **km01, km02, km03** for control plane nodes
  - **kube01, kube02, kube03** for worker nodes
- The terraform configurations at `tf/kubernetes/terraform.tfvars` showed the OLD planned IPs (11-13) but these were never deployed
- The actual deployment used Kubespray with the IPs documented above

**Needs Resolution:** No - Resolved

**Impact:** High - incorrect IPs will break load balancing

---

### OQ-5: Exact Worker Node IPs

**Question:** What are the exact IP addresses for kube04, kube05, kube06?

**Context:**
- Need precise IP addresses for NodePort upstream configuration
- Based on pattern, likely 192.168.10.14-16 but needs confirmation

**Assumption:** Based on existing infrastructure pattern:
- kube04: 192.168.10.14
- kube05: 192.168.10.15
- kube06: 192.168.10.16

**STATUS: RESOLVED**

**Resolution:**
Based on the kubespray inventory analysis, there is NO kube04-06 in the deployment.

**ACTUAL WORKER NODES:**
- **kube01**: 192.168.10.237 (VM on pve3, 8 cores, 16GB RAM)
- **kube02**: 192.168.10.238 (VM on pve1, 8 cores, 16GB RAM)
- **kube03**: 192.168.10.239 (VM on pve2, 8 cores, 16GB RAM)

**Cluster Architecture Summary:**
- **3 control plane nodes**: km01 (234), km02 (235), km03 (236)
- **3 worker nodes**: kube01 (237), kube02 (238), kube03 (239)
- **Total**: 6-node cluster (not the 9-node cluster mentioned in original spec assumptions)

**Configuration Impact:**
- The nginx configuration must use **kube01-03** at IPs **237-239** for NodePort service backends
- The nginx stream configuration must use **km01-03** at IPs **234-236** for K8s API backends

**Needs Resolution:** No - Resolved

**Impact:** High - incorrect IPs will break NodePort load balancing

---

### OQ-6: NodePort Service Inventory

**Question:** Which NodePort services should be configured initially?

**Context:**
- Existing playbook shows ArgoCD and Traefik
- Need to determine complete list of NodePort services to expose
- Each service requires separate upstream and server block

**Current Known Services:**
- ArgoCD HTTP: port 8080 → NodePort 31160
- ArgoCD HTTPS: port 8443 → NodePort 32442
- Traefik HTTP: port 80 → NodePort 31469
- Traefik HTTPS: port 443 → NodePort 31685

**STATUS: RESOLVED**

**Resolution:**
- **Initial Services**: Start with the four services documented above (ArgoCD HTTP/HTTPS, Traefik HTTP/HTTPS)
- **Configuration Source**: Use existing service definitions from `ansible/playbooks/setup_nginx_lb.yml`
- **Extensibility**: Design nginx configuration to be easily extensible for adding new NodePort services via Ansible variables
- **Future Services**: Additional services can be added by updating the `services` array in Ansible group_vars

**Needs Resolution:** No - Resolved (start with these, make extensible for adding more)

**Impact:** Medium - affects initial configuration completeness

---

### OQ-7: Nginx Log Retention and Rotation

**Question:** What log retention policy should be implemented?

**Context:**
- Nginx will generate access and error logs
- Need to balance disk space with debugging capability
- Consider integration with Elasticsearch

**Options:**
1. Default logrotate (daily, keep 14 days)
2. Custom retention (adjust based on load)
3. Forward to Elasticsearch (centralized logging)

**Recommendation:** Default logrotate + optional Elasticsearch forwarding

**STATUS: RESOLVED**

**Resolution:**
- **Decision**: Use default Ubuntu logrotate configuration (daily rotation, keep 14 days)
- **Rationale**: Sufficient for homelab environment, can be adjusted post-deployment based on actual log volume
- **Future Enhancement**: Can add Elasticsearch log forwarding if needed for centralized monitoring

**Needs Resolution:** No - Default approach acceptable

**Impact:** Low - can be adjusted post-deployment

---

### OQ-8: Backup and Recovery Strategy

**Question:** How should load balancer configuration and state be backed up?

**Context:**
- Nginx config should be in git (via Ansible templates)
- Corosync configuration needs backup
- VIP state is transient

**Strategy:**
- Nginx config: Git via Ansible (already covered)
- Corosync config: Include in Ansible playbook (idempotent)
- No additional backup needed (infrastructure as code)

**STATUS: RESOLVED**

**Resolution:**
- **Approach**: Infrastructure as Code provides implicit backup
- **Nginx Configuration**: Stored in git as Jinja2 template, deployed via Ansible
- **Corosync Configuration**: Stored in git as Jinja2 template, deployed via Ansible
- **Recovery**: Re-run Ansible playbook to restore configuration
- **State**: VIP assignment is transient and managed by corosync, no backup needed

**Needs Resolution:** No - documented approach is sufficient

**Impact:** Low - IaC provides implicit backup

---

## Additional Research Needed

### AR-1: Corosync Network Best Practices

**Topic:** Optimal corosync network configuration for 2-node cluster

**Research Areas:**
- Corosync token timeout values for cluster stability
- Network interface bonding/redundancy for cluster communication
- UDP vs UDPU transport mode selection

**STATUS: RESOLVED**

**Resolution:**
- **Transport**: Use UDP unicast (UDPU) for 2-node cluster (more reliable than multicast)
- **Token Timeout**: Use default 1000ms token timeout (sufficient for single subnet)
- **Network**: Single network interface is acceptable for homelab (both nodes on same subnet)
- **Configuration**: Will use standard corosync defaults with two_node quorum policy

**Priority:** Medium

**Timeframe:** Before Ansible implementation

**Resources:**
- ClusterLabs documentation
- Corosync performance tuning guides

---

### AR-2: Nginx Stream Module Performance

**Topic:** Performance characteristics of nginx stream module for K8s API

**Research Areas:**
- Connection limits and tuning
- Proxy buffer sizes for large list operations
- Timeout values for long-running watch operations

**STATUS: ACCEPTED**

**Resolution:**
- **Initial Configuration**: Use recommended timeouts from spec:
  - `proxy_timeout=10m` for long-lived kubectl operations
  - `proxy_connect_timeout=10s` for initial connection
- **Monitoring**: Monitor post-deployment and adjust based on actual usage
- **Tuning**: Can be adjusted via Ansible playbook re-run if needed

**Priority:** Low

**Timeframe:** Can be tuned post-deployment based on monitoring

**Resources:**
- Nginx stream module documentation
- Kubernetes API client behavior documentation

---

### AR-3: Proxmox VM Placement Anti-Affinity

**Topic:** How to ensure nginx-lb VMs are on different Proxmox hosts

**STATUS: RESOLVED**

**Resolution:**
- **Method**: Manual target_node assignment in terraform.tfvars
- **nginx-lb01**: Set `target_node = "pve1"` in terraform configuration
- **nginx-lb02**: Set `target_node = "pve2"` in terraform configuration
- **Verification**: Review terraform plan output to confirm different hosts before apply
- **Rationale**: Proxmox provider does not support anti-affinity rules, manual assignment is the standard approach

**Priority:** Medium

**Timeframe:** During Terraform module design

**Resources:**
- Terraform proxmox provider documentation
- Proxmox HA documentation

---

### AR-4: Corosync Fence Agent Options

**Topic:** Available fence agents for Proxmox if STONITH is desired

**Research Areas:**
- fence_pve agent capabilities
- Proxmox API requirements for fencing
- Configuration complexity vs benefit

**STATUS: DEFERRED**

**Resolution:**
- **Decision**: STONITH disabled (OQ-3), fence agent research not needed
- **Future**: Can be revisited if split-brain issues occur in production
- **Documentation**: Note that fence_pve exists if STONITH becomes necessary

**Priority:** Low (if STONITH disabled)

**Timeframe:** Post-deployment if needed

**Resources:**
- ClusterLabs fence agent documentation
- Proxmox API documentation

---

## Deferred Decisions

### DD-1: Three-Node Cluster Expansion

**Decision:** Start with two nodes, evaluate need for third node based on experience

**Rationale:**
- Two nodes sufficient for homelab HA requirements
- Can add third node later if needed
- Reduces initial resource consumption

**Reevaluation Trigger:**
- Frequent split-brain issues
- Need for true quorum without special policies
- Expansion of homelab infrastructure

---

### DD-2: Active-Active Load Balancing

**Decision:** Implement active-passive with VIP, defer active-active

**Rationale:**
- Active-passive simpler to implement and maintain
- Active-active requires BGP/ECMP or DNS round-robin
- Network infrastructure may not support BGP
- Homelab load doesn't require active-active capacity

**Reevaluation Trigger:**
- Capacity constraints on single load balancer
- Network infrastructure gains BGP capability
- Need for load distribution beyond failover

---

### DD-3: WAF and Security Features

**Decision:** Implement basic load balancing, defer WAF features

**Rationale:**
- Internal homelab network has lower threat model
- WAF adds complexity and maintenance
- Can add nginx ModSecurity later if needed

**Reevaluation Trigger:**
- Exposure of services to external network
- Security incident or audit requirement
- Addition of untrusted users to network

---

### DD-4: Automated Certificate Management

**Decision:** Use existing step-certificates infrastructure, no additional automation

**Rationale:**
- K8s API uses passthrough (no certificates at LB)
- NodePort services can use existing certificates
- No immediate need for automated certificate provisioning at LB

**Reevaluation Trigger:**
- Addition of SSL termination features
- Migration away from step-certificates
- Need for Let's Encrypt integration

---

### DD-5: Dynamic NodePort Discovery

**Decision:** Statically configure NodePort services, defer dynamic discovery

**Rationale:**
- Homelab has relatively static service configuration
- Dynamic discovery adds significant complexity
- Manual configuration is acceptable for low change rate

**Reevaluation Trigger:**
- Frequent NodePort service changes
- Integration with service mesh
- Need for automatic service exposure

---

## Implementation Notes

### Critical Path Items - ALL RESOLVED

All critical items have been resolved:

1. **OQ-4: Control Plane IPs** - RESOLVED: km01 (234), km02 (235), km03 (236)
2. **OQ-5: Worker Node IPs** - RESOLVED: kube01 (237), kube02 (238), kube03 (239)
3. **OQ-1: Proxmox Target Nodes** - RESOLVED: nginx-lb01 on pve1, nginx-lb02 on pve2
4. **AR-3: VM Anti-Affinity** - RESOLVED: Manual target_node assignment

### Implementation Ready

All questions resolved with concrete decisions:

1. **OQ-2: Quorum Policy** - Use `two_node: 1` (standard approach)
2. **OQ-3: STONITH** - Disable (acceptable for homelab)
3. **OQ-6: NodePort Services** - Start with ArgoCD + Traefik, extensible design
4. **OQ-7: Log Retention** - Use default logrotate

### Post-Deployment Tuning

Items that can be addressed after initial deployment:

1. **AR-2: Performance Tuning** - Monitor and adjust based on actual usage
2. **OQ-7: Log Management** - Can optimize based on actual log volume
3. **DD-1 through DD-5** - All deferred decisions can be revisited later

---

## Resolution Tracking

| Question | Status | Resolved By | Resolution |
|----------|--------|-------------|------------|
| OQ-1 | RESOLVED | Codebase Analysis | nginx-lb01 on pve1, nginx-lb02 on pve2 |
| OQ-2 | RESOLVED | Best Practice | Use two_node: 1 quorum policy |
| OQ-3 | RESOLVED | Homelab Simplicity | Disable STONITH |
| OQ-4 | RESOLVED | Kubespray Inventory | km01-03: 234-236 (control plane) |
| OQ-5 | RESOLVED | Kubespray Inventory | kube01-03: 237-239 (workers) |
| OQ-6 | RESOLVED | Existing Playbook | ArgoCD + Traefik, extensible |
| OQ-7 | RESOLVED | Default Approach | Use default logrotate |
| OQ-8 | RESOLVED | IaC Principle | Infrastructure as Code provides backup |
| AR-1 | RESOLVED | Best Practice | UDPU transport, default timeouts |
| AR-2 | ACCEPTED | Monitor Later | Start with spec values, tune post-deploy |
| AR-3 | RESOLVED | Manual Assignment | Use target_node in terraform.tfvars |
| AR-4 | DEFERRED | STONITH Disabled | Not needed, can revisit later |

---

## Architecture Summary

Based on all resolved questions, here is the final architecture:

### Load Balancer Cluster
- **nginx-lb01**: 192.168.10.251 on pve1 (VMID 250)
- **nginx-lb02**: 192.168.10.252 on pve2 (VMID 251)
- **Virtual IP**: 192.168.10.250 (cluster endpoint)
- **HA**: Corosync with two_node quorum, STONITH disabled

### Kubernetes Control Plane (API Server Backends)
- **km01**: 192.168.10.234 (bare metal)
- **km02**: 192.168.10.235 (VM on pve1)
- **km03**: 192.168.10.236 (VM on pve2)
- **Nginx Stream Block**: Port 6443 TCP passthrough to km01-03

### Kubernetes Worker Nodes (NodePort Backends)
- **kube01**: 192.168.10.237 (VM on pve3)
- **kube02**: 192.168.10.238 (VM on pve1)
- **kube03**: 192.168.10.239 (VM on pve2)
- **Nginx HTTP Block**: NodePort services proxied to kube01-03

### Initial NodePort Services
- **ArgoCD HTTP**: 8080 → 31160 (kube01-03)
- **ArgoCD HTTPS**: 8443 → 32442 (kube01-03)
- **Traefik HTTP**: 80 → 31469 (kube01-03)
- **Traefik HTTPS**: 443 → 31685 (kube01-03)

---

## Next Steps

All planning questions resolved. Ready to proceed with implementation:

1. **Task Group 1 Complete** - All IP addresses and infrastructure decisions confirmed
2. **Task Group 2 Ready** - Can proceed with Terraform infrastructure provisioning
3. **Task Group 3 Ready** - Ansible inventory structure defined
4. **Task Group 4 Ready** - Nginx and Corosync configuration parameters confirmed
5. **Task Group 5 Ready** - Kubeconfig update strategy defined
6. **Task Group 6 Ready** - Testing and validation approach defined
