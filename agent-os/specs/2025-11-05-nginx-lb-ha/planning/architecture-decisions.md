# Architecture Decisions: Nginx Load Balancer HA

This document captures key technical decisions made during requirements gathering and provides rationale for architectural choices.

## Overview

The nginx load balancer HA feature provides a highly available, dual-purpose load balancing solution for the Kubernetes homelab infrastructure. It serves two critical functions:

1. Load balancing Kubernetes API server traffic across control plane nodes
2. Load balancing NodePort service traffic across worker nodes

The solution uses a two-node active-passive HA configuration with automatic failover.

## Key Architectural Decisions

### AD-1: Dual-Purpose Load Balancer Design

**Decision:** Implement a single load balancer infrastructure that serves both Kubernetes API traffic and NodePort services, rather than deploying separate load balancers.

**Rationale:**
- **Resource Efficiency**: Reduces VM count and resource consumption in homelab environment
- **Operational Simplicity**: Single infrastructure to manage, monitor, and troubleshoot
- **Cost Effective**: Minimizes overhead while meeting all functional requirements
- **Clear Separation**: Different nginx blocks (stream vs http) provide clear logical separation
- **Scalability**: Can easily split into separate load balancers in future if needed

**Implementation:**
- Stream block (Layer 4) for K8s API server traffic
- HTTP block (Layer 7) for NodePort service traffic
- Single nginx configuration file with clearly separated sections

**Alternatives Considered:**
- **Separate Load Balancers**: Would require 4 VMs total (2 for API, 2 for NodePort), excessive for homelab
- **Single-Purpose API Only**: Would not address NodePort accessibility, leaving gap in infrastructure
- **External Load Balancer Service**: Cloud-based solutions inappropriate for homelab environment

---

### AD-2: Corosync for HA Instead of Keepalived

**Decision:** Use Corosync with Pacemaker for VIP management and cluster coordination instead of keepalived.

**Rationale:**
- **User Preference**: Explicit requirement from user to use corosync
- **Enterprise-Grade**: Corosync/Pacemaker is the industry standard for HA clustering
- **Rich Feature Set**: Provides comprehensive cluster resource management beyond just VIP
- **Extensibility**: Easier to add additional cluster resources in future
- **Better Monitoring**: Superior cluster state visibility and diagnostics
- **Resource Constraints**: More sophisticated resource constraint management

**Implementation:**
- Corosync for cluster communication and membership
- Pacemaker for resource management (VIP as cluster resource)
- Crm shell for cluster configuration and management
- STONITH disabled (acceptable for homelab environment)

**Alternatives Considered:**
- **Keepalived**: Simpler, lighter-weight, but less feature-rich and not preferred by user
- **HAProxy + Keepalived**: Additional complexity without significant benefit
- **Consul**: Over-engineered for this use case, would require additional service discovery infrastructure
- **Cloud Provider LB**: Not applicable to on-premises homelab environment

---

### AD-3: Least Connections Algorithm for API Load Balancing

**Decision:** Use `least_conn` load balancing algorithm for Kubernetes API server traffic instead of round-robin or other algorithms.

**Rationale:**
- **Long-Lived Connections**: kubectl commands and watch operations create long-lived connections
- **Fair Distribution**: Prevents overloading of any single control plane node
- **Better Resource Utilization**: Distributes load based on actual connection count
- **Watch Stream Handling**: More equitable distribution of Kubernetes watch streams
- **List Operation Balance**: Large list operations won't overwhelm single backend

**Implementation:**
```nginx
upstream k8s_api_servers {
    least_conn;
    server <control-plane-1>:6443 max_fails=2 fail_timeout=30s;
    server <control-plane-2>:6443 max_fails=2 fail_timeout=30s;
    server <control-plane-3>:6443 max_fails=2 fail_timeout=30s;
}
```

**Alternatives Considered:**
- **Round-Robin**: Default, but unfair with long-lived connections
- **IP Hash**: Sticky sessions unnecessary for stateless API server
- **Random**: Provides no benefit over round-robin for this use case
- **Weighted**: All control plane nodes have identical capacity

---

### AD-4: Worker-Only Backend for NodePort Services

**Decision:** Configure NodePort service load balancing to target worker nodes (kube04-06) exclusively, not control plane nodes.

**Rationale:**
- **Best Practice**: Separation of control plane and data plane workloads
- **Resource Protection**: Preserves control plane resources for cluster management
- **Workload Isolation**: Application traffic doesn't impact cluster operations
- **Kubespray Pattern**: Follows kubespray deployment model with dedicated worker nodes
- **Failure Domain Separation**: Control plane failures don't affect application traffic
- **Taint/Toleration Alignment**: Worker nodes are designated for application workloads

**Implementation:**
```nginx
upstream nodeport_service {
    least_conn;
    server 192.168.10.x:30xxx max_fails=2 fail_timeout=30s;  # kube04
    server 192.168.10.x:30xxx max_fails=2 fail_timeout=30s;  # kube05
    server 192.168.10.x:30xxx max_fails=2 fail_timeout=30s;  # kube06
}
```

**Alternatives Considered:**
- **All Nodes**: Would mix control plane and data plane traffic, violating best practices
- **Control Plane Only**: Would prevent workload scaling and violate Kubernetes patterns
- **Dynamic Backend Discovery**: Over-engineered for static homelab cluster

---

### AD-5: TCP Passthrough for Kubernetes API Traffic

**Decision:** Use TCP stream mode (Layer 4 passthrough) for Kubernetes API server traffic instead of HTTPS proxy or SSL termination.

**Rationale:**
- **End-to-End TLS**: Maintains TLS connection from client directly to API server
- **Certificate Validation**: Clients can validate API server certificates directly
- **Security**: No certificate management required at load balancer
- **Simplicity**: Avoids complex certificate rotation and renewal at load balancer
- **kubectl Compatibility**: Full compatibility with kubectl certificate-based authentication
- **RBAC Preservation**: Client certificate authentication works transparently
- **Audit Trail**: API server logs show actual client identity, not load balancer

**Implementation:**
```nginx
stream {
    upstream k8s_api_servers {
        least_conn;
        server <backend>:6443 max_fails=2 fail_timeout=30s;
    }

    server {
        listen 6443;
        proxy_pass k8s_api_servers;
        proxy_timeout 10m;
        proxy_connect_timeout 10s;
    }
}
```

**Alternatives Considered:**
- **SSL Termination**: Would break client certificate authentication, require complex certificate management
- **SSL Passthrough with SNI**: Unnecessary complexity for single API endpoint
- **HTTP/2 Proxy**: Would require certificate management and break end-to-end TLS

---

### AD-6: Two-Node HA Cluster Configuration

**Decision:** Deploy exactly two nginx load balancer nodes with active-passive failover using a Virtual IP (VIP).

**Rationale:**
- **Minimum HA**: Two nodes is minimum for high availability
- **Resource Efficiency**: Three-node consensus unnecessary for homelab scale
- **Split-Brain Prevention**: Corosync quorum with 2 nodes plus quorate policy
- **Cost Effective**: Each node is 2 cores / 2GB RAM, minimal resource overhead
- **Sufficient Redundancy**: One node failure still maintains service
- **Simplified Operations**: Fewer nodes to manage, patch, and monitor

**Configuration:**
- **nginx-lb01**: 192.168.10.251 (Primary/preferred node)
- **nginx-lb02**: 192.168.10.252 (Secondary node)
- **VIP**: 192.168.10.250 (Shared cluster IP)

**Failover Behavior:**
- VIP automatically moves to secondary when primary fails
- VIP returns to primary when it recovers (preferred node)
- No manual intervention required
- Both nodes always configured identically

**Alternatives Considered:**
- **Single Node**: No high availability, single point of failure
- **Three+ Nodes**: Over-engineered for homelab, wastes resources, adds complexity
- **Active-Active with BGP/ECMP**: Requires router configuration, excessive complexity
- **Cloud LB Service**: Not applicable to on-premises homelab

---

### AD-7: Separate Terraform Module Structure

**Decision:** Create dedicated `tf/nginx-lb/` directory with independent Terraform state file following existing pattern.

**Rationale:**
- **Follows Pattern**: Consistent with existing kubernetes/, lab/, home-apps/ structure
- **State Isolation**: Changes to load balancer don't affect other infrastructure
- **Lifecycle Independence**: Can deploy, modify, destroy without touching other environments
- **Clear Ownership**: Obvious location for load balancer infrastructure code
- **Team Workflow**: Multiple engineers can work on different infrastructure components

**Directory Structure:**
```
tf/nginx-lb/
├── main.tf              # VM module instantiation for both nodes
├── variables.tf         # Input variables
├── outputs.tf          # Output values (IPs, etc.)
├── provider.tf         # Proxmox provider configuration
├── versions.tf         # Provider version constraints
├── terraform.tfvars    # Variable values (both VMs, IPs, VIP config)
└── README.md           # Documentation
```

**Alternatives Considered:**
- **Add to kubernetes/**: Would couple load balancer state with cluster state
- **Single tf/ root**: Would create monolithic state file, increases blast radius
- **No Terraform**: Manual VM creation inconsistent with infrastructure-as-code approach

---

### AD-8: Manual Local Kubeconfig Updates

**Decision:** Provide manual instructions for updating local workstation kubeconfig rather than attempting automation.

**Rationale:**
- **Security**: Ansible shouldn't have access to local workstation
- **User Control**: Users retain full control over local configuration
- **Simplicity**: Clear, documented manual steps are safer than automation
- **Cross-Platform**: Works for macOS, Linux, Windows without platform-specific automation
- **One-Time Operation**: Manual update is acceptable for infrequent operation
- **Backup Control**: Users can backup locally before modification

**Implementation:**
- Clear documentation with step-by-step instructions
- Backup procedure included
- Validation steps provided
- Rollback instructions documented

**Automated Part:**
- Ansible playbook updates kubeconfig on cluster nodes
- All remote hosts automatically reconfigured

**Alternatives Considered:**
- **Ansible to Local Mac**: Security concern, requires local Ansible agent/SSH
- **Shell Script**: Still requires running untrusted code on workstation
- **kubectl Plugin**: Over-engineered for one-time update
- **Config Management Tool**: Inappropriate for personal workstation

---

### AD-9: Health Check Configuration

**Decision:** Use `max_fails=2` and `fail_timeout=30s` for backend health checks, matching existing configuration patterns.

**Rationale:**
- **Proven Configuration**: Already in use for existing NodePort load balancing
- **Quick Failover**: Detects failures within 30 seconds with 2 failed attempts
- **Avoids Flapping**: Two failures prevent marking healthy backend as down from single timeout
- **API Server Appropriate**: Kubernetes API server typically responds quickly or is completely down
- **Fast Recovery**: 30s timeout allows quick return to service after recovery

**Implementation:**
```nginx
server <backend-ip>:<port> max_fails=2 fail_timeout=30s;
```

**Behavior:**
- After 2 consecutive failures, backend marked as down
- Backend unavailable for 30 seconds
- After 30s, next successful request marks backend as up
- Applies to both API server and NodePort backends

**Alternatives Considered:**
- **Active Health Checks**: Nginx Plus feature, not available in open source
- **Longer Timeout**: Would delay failover unnecessarily
- **Single Failure**: Too sensitive, would cause flapping
- **External Monitoring**: Unnecessary complexity for simple health checking

---

### AD-10: Network and IP Address Allocation

**Decision:** Allocate IP addresses in 192.168.10.250-252 range for load balancer infrastructure.

**IP Allocation:**
- **192.168.10.250**: VIP (Virtual IP) - Client access point
- **192.168.10.251**: nginx-lb01 - Primary physical node
- **192.168.10.252**: nginx-lb02 - Secondary physical node

**Rationale:**
- **Sequential Allocation**: Follows existing homelab IP allocation pattern
- **Memorable Addresses**: .250-.252 range easy to remember and document
- **Avoids Conflicts**: Above K8s nodes (.11-.16) and Elasticsearch (.31-.39)
- **VIP First**: .250 as VIP is logical (clients use lowest address)
- **Reserved Range**: Could extend to .253-.254 if future expansion needed

**Network Configuration:**
- Network: 192.168.10.0/24
- Gateway: 192.168.10.1
- DNS: 192.168.10.1
- Domain: lab.thewortmans.org

**Alternatives Considered:**
- **DHCP Reservation**: Not suitable for infrastructure components
- **Higher Range (.240+)**: No benefit, .250 range is clear and available
- **Separate VLAN**: Over-engineered for homelab, adds network complexity

---

## Implementation Patterns

### Terraform Pattern

**Module Usage:**
```hcl
module "nginx_lb01" {
  source = "../modules/proxmox_vm"
  name   = "nginx-lb01"
  ipconfig0 = "ip=192.168.10.251/24,gw=192.168.10.1"
  # ... other configuration
}

module "nginx_lb02" {
  source = "../modules/proxmox_vm"
  name   = "nginx-lb02"
  ipconfig0 = "ip=192.168.10.252/24,gw=192.168.10.1"
  # ... other configuration
}
```

**Vault Integration:**
```hcl
data "vault_kv_secret_v2" "proxmox" {
  mount = "kv"
  name  = "proxmox"
}

data "vault_kv_secret_v2" "ssh_keys" {
  mount = "kv"
  name  = "ssh_keys"
}

locals {
  ciuser     = data.vault_kv_secret_v2.proxmox.data["ciuser"]
  cipassword = data.vault_kv_secret_v2.proxmox.data["cipassword"]
  sshkeys    = data.vault_kv_secret_v2.ssh_keys.data["public_key"]
}
```

### Ansible Pattern

**Inventory Structure:**
```ini
[nginx_lb]
nginx-lb01 ansible_host=192.168.10.251
nginx-lb02 ansible_host=192.168.10.252

[nginx_lb:vars]
cluster_vip=192.168.10.250
cluster_name=nginx-lb-cluster
```

**Playbook Structure:**
```yaml
- name: Configure nginx Load Balancer HA
  hosts: nginx_lb
  become: true
  tasks:
    - name: Install packages
      # Install nginx, corosync, pacemaker

    - name: Configure nginx
      # Deploy dual-purpose configuration

    - name: Setup corosync cluster
      # Configure HA with VIP
```

### Nginx Configuration Pattern

**File Structure:**
```
/etc/nginx/
├── nginx.conf                    # Main configuration
├── conf.d/
│   ├── k8s-api-stream.conf      # K8s API (stream block)
│   └── nodeport-http.conf       # NodePort services (http block)
```

**Configuration Separation:**
- Stream block for K8s API (Layer 4 TCP passthrough)
- HTTP block for NodePort services (Layer 7 proxying)
- Clear comments and section markers
- Jinja2 templating for dynamic backend generation

---

## Security Considerations

### Certificate Management
- K8s API: End-to-end TLS, no certificate management at LB
- NodePort services: Use existing step-certificates infrastructure
- Corosync: Uses pre-shared key for cluster authentication

### Access Control
- SSH access: Key-based authentication only via cloud-init
- Nginx: No authentication at load balancer layer
- Corosync: Restricted to cluster network

### Network Security
- All services on internal network only (192.168.10.0/24)
- No external exposure required
- Firewall rules managed at Proxmox level

---

## Monitoring and Observability

### Health Monitoring
- Nginx passive health checks (max_fails/fail_timeout)
- Corosync cluster status monitoring
- VIP status tracking

### Integration Points
- Existing Prometheus/Grafana stack can scrape nginx metrics
- Corosync cluster state exposed for monitoring
- Logs sent to existing Elasticsearch/Kibana

### Metrics to Track
- Backend health status
- Request distribution across backends
- Failover events
- VIP location and transitions
- Connection counts and duration

---

## Testing and Validation

### Infrastructure Testing
- Terraform plan validation
- VM provisioning verification
- Network connectivity validation

### HA Testing
- Primary node shutdown test
- VIP failover verification
- Service continuity validation
- Failback testing

### Load Balancer Testing
- K8s API access through VIP
- kubectl operation validation
- NodePort service accessibility
- Health check behavior verification

### Operational Testing
- Ansible playbook idempotency
- Configuration updates without downtime
- Rolling updates of load balancer nodes

---

## Future Considerations

### Potential Enhancements
- Active-active configuration with BGP/ECMP
- Three-node cluster for true quorum
- Advanced nginx metrics and dashboards
- Automated certificate rotation integration
- Integration with service mesh (if deployed)

### Known Limitations
- Two-node quorum requires careful split-brain handling
- Manual local kubeconfig updates
- No automated NodePort discovery (manual configuration)
- Single network interface per node

### Evolution Path
- Start: Two-node HA with VIP
- Future: Could add third node if needed
- Future: Could integrate with external DNS
- Future: Could add WAF capabilities if required

---

## References

### Documentation
- Nginx Stream Module: http://nginx.org/en/docs/stream/ngx_stream_core_module.html
- Nginx HTTP Load Balancing: http://nginx.org/en/docs/http/load_balancing.html
- Corosync Documentation: https://clusterlabs.org/corosync.html
- Pacemaker Documentation: https://clusterlabs.org/pacemaker/

### Related Infrastructure
- Kubernetes cluster: kube01-06 (192.168.10.11-16)
- Proxmox VM provisioning: modules/proxmox_vm
- Existing playbooks: ansible/playbooks/
- Vault secrets: kv/proxmox, kv/ssh_keys
