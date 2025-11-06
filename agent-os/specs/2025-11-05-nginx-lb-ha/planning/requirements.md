# Spec Requirements: Nginx Load Balancer HA for Kubernetes

## Initial Description

Deploy a dedicated load balancer node for Kubernetes API server high availability. This involves:

1. Creating a Terraform module for nginx-lb VM provisioning on Proxmox
2. Implementing an Ansible playbook for nginx configuration targeting all control plane nodes (kube01, kube02, kube03)
3. Updating kubeconfig to use the load balancer endpoint instead of direct node access

### Context from the Codebase

- **Current K8s cluster**: 3 control plane nodes (kube01-03) and 3 worker nodes (kube04-06)
- **Infrastructure**: Proxmox virtualization managed via Terraform
- **Configuration management**: Ansible playbooks
- **Cluster deployment**: Recently deployed using Kubespray
- **Network**: 192.168.10.0/24 range
- **Existing Terraform modules**: Located in tf/ directory
- **Existing Ansible playbooks**: Located in ansible/ directory

## Requirements Discussion

### First Round Questions

**Q1:** What will the load balancer be used for? Just the Kubernetes API server (port 6443), or also for NodePort services?

**Answer:** Enhance to do BOTH jobs:
- Kubernetes API server (port 6443) to control plane nodes (km01, km02, km03)
- NodePort services (30000-32767) to worker nodes only (kube04-06)

**Q2:** What VM specifications should the nginx load balancer have?

**Answer:** 2 cores, 2GB RAM, 20GB disk - Acceptable

**Q3:** What IP address should the load balancer use?

**Answer:** Use 192.168.10.250 (it was never actually deployed, so reuse this IP)

**Q4:** What load balancing algorithm should we use?

**Answer:** `least_conn` (recommended and accepted)

**Q5:** What health check configuration should we use?

**Answer:** Match existing config - `max_fails=2`, `fail_timeout=30s`

**Q6:** How should we handle kubeconfig updates?

**Answer:**
- Ansible playbook to update kubeconfig on remote hosts
- Manual instructions for updating local MacBook kubeconfig (don't try to automate MacBook updates)

**Q7:** Should we implement SSL/TLS termination at the load balancer?

**Answer:** TCP passthrough (stream mode) - Confirmed correct approach

**Q8:** How many nginx load balancer nodes should we deploy for HA?

**Answer:** Deploy TWO nginx nodes with:
- Shared cluster IP (VIP): 192.168.10.250
- Individual node IPs: 192.168.10.251 (nginx-lb01), 192.168.10.252 (nginx-lb02)
- Failover using **corosync** (not keepalived)
- Node names: nginx-lb01, nginx-lb02

**Q9:** Should we create a new Terraform module or add to an existing one?

**Answer:** Create new module at `tf/nginx-lb/`

**Q10:** Do you have any design mockups, wireframes, or screenshots that could help guide the development?

**Answer:** None provided

### Existing Code to Reference

**Similar Features Identified:**

Based on the investigation, there are existing patterns to reference:

- **Terraform Module Pattern**: `tf/kubernetes/`, `tf/lab/`, `tf/home-apps/` - All use the shared `modules/proxmox_vm` module for VM provisioning
- **Ansible Playbook Pattern**: `ansible/playbooks/` directory contains existing playbooks for cluster setup
- **Inventory Structure**: `ansible/inventory/` contains group-based inventory files for different environments
- **Existing nginx configuration**: `ansible/playbooks/setup_nginx_lb.yml` and `ansible/templates/nginx-lb.conf.j2` already exist and need to be enhanced for dual-purpose use and HA
- **Terraform module skeleton**: `tf/nginx-lb/` directory already exists with initial configuration

**Components to potentially reuse:**
- Existing proxmox_vm module from `tf/modules/proxmox_vm/`
- Ansible inventory pattern from `ansible/inventory/lab` and other inventory files
- Nginx configuration template pattern from `ansible/templates/nginx-lb.conf.j2`
- Vault integration pattern for secrets from existing terraform configurations

**Backend logic to reference:**
- Cloud-init configuration pattern from existing VM modules
- Ansible playbook structure from `ansible/playbooks/`
- Vault secret retrieval using `data.vault_kv_secret_v2` resources

### Visual Assets

No visual assets provided.

## Requirements Summary

### Functional Requirements

#### Dual-Purpose Load Balancing

**Kubernetes API Server Load Balancing:**
- Load balance port 6443 to ALL control plane nodes (kube01, kube02, kube03)
- Use TCP stream mode (Layer 4 passthrough, no SSL termination)
- Maintain TLS end-to-end from client to API server
- Health checks: `max_fails=2`, `fail_timeout=30s`
- Load balancing algorithm: `least_conn`

**NodePort Services Load Balancing:**
- Load balance NodePort range (30000-32767) to worker nodes ONLY (kube04-06)
- Use HTTP/HTTPS proxy mode (Layer 7) for NodePort services
- Support WebSocket connections
- Health checks: `max_fails=2`, `fail_timeout=30s`
- Load balancing algorithm: `least_conn`

#### High Availability Configuration

**Two-Node HA Cluster:**
- nginx-lb01: Primary node (192.168.10.251)
- nginx-lb02: Secondary node (192.168.10.252)
- Virtual IP (VIP): 192.168.10.250 (shared cluster IP)

**Failover Management:**
- Use **corosync** for cluster management and VIP failover
- Automatic failover when primary node fails
- No manual intervention required for failover
- Both nodes actively configured with same nginx configuration

**VM Specifications (per node):**
- 2 CPU cores
- 2GB RAM
- 20GB disk storage
- Target node: Proxmox cluster
- Network: 192.168.10.0/24
- Gateway: 192.168.10.1
- DNS: 192.168.10.1

#### Infrastructure Provisioning

**Terraform Module:**
- Location: `tf/nginx-lb/`
- Provision TWO VMs (nginx-lb01, nginx-lb02)
- Use shared `modules/proxmox_vm` module
- Integrate with HashiCorp Vault for secrets (SSH keys, cloud-init credentials)
- Standard cloud-init configuration with Ubuntu 25.04 template
- Static IP configuration for both nodes plus VIP

**Resource Configuration:**
- VMID range: To be assigned sequentially
- Clone: ubuntu-25.04 template
- Storage: "tank" NFS storage
- Network: virtio model on vmbr0 bridge
- Tags: "nginx", "loadbalancer", "ha"

#### Configuration Management

**Ansible Playbook Requirements:**

1. **Nginx Installation and Configuration:**
   - Install nginx on both nodes
   - Configure dual-purpose load balancing (API server + NodePort)
   - Generate configuration from Jinja2 template
   - Enable and start nginx service

2. **Corosync HA Setup:**
   - Install and configure corosync on both nodes
   - Configure VIP (192.168.10.250) as shared resource
   - Set up automatic failover
   - Configure node priorities (nginx-lb01 as preferred primary)

3. **Kubeconfig Update (Remote Hosts):**
   - Update kubeconfig on all cluster nodes to use VIP (192.168.10.250:6443)
   - Backup existing kubeconfig before modification
   - Validate connectivity after update

4. **Manual Instructions (Local MacBook):**
   - Provide clear documentation for manually updating local kubeconfig
   - Include backup instructions
   - Include validation steps

**Inventory Management:**
- Create new inventory group: `[nginx_lb]`
- Include both nginx-lb01 and nginx-lb02
- Define group variables for VIP and cluster configuration

#### Nginx Configuration Structure

**Stream Block (Layer 4 - K8s API):**
```
stream {
    upstream k8s_api_servers {
        least_conn;
        server 192.168.10.x:6443 max_fails=2 fail_timeout=30s;  # kube01
        server 192.168.10.x:6443 max_fails=2 fail_timeout=30s;  # kube02
        server 192.168.10.x:6443 max_fails=2 fail_timeout=30s;  # kube03
    }

    server {
        listen 6443;
        proxy_pass k8s_api_servers;
        proxy_timeout 10m;
        proxy_connect_timeout 10s;
    }
}
```

**HTTP Block (Layer 7 - NodePort Services):**
```
http {
    upstream nodeport_service_name {
        least_conn;
        server 192.168.10.x:30xxx max_fails=2 fail_timeout=30s;  # kube04
        server 192.168.10.x:30xxx max_fails=2 fail_timeout=30s;  # kube05
        server 192.168.10.x:30xxx max_fails=2 fail_timeout=30s;  # kube06
    }

    server {
        listen 80;  # or other standard ports
        location / {
            proxy_pass http://nodeport_service_name;
            # Standard proxy headers
            # WebSocket support
        }
    }
}
```

### Reusability Opportunities

**Components that might exist already:**
- VM provisioning module: `modules/proxmox_vm/` (confirmed exists)
- Ansible playbook structure and patterns from existing playbooks
- Vault integration for credential management
- Cloud-init configuration patterns
- Inventory group management patterns

**Backend patterns to investigate:**
- Existing nginx configuration template needs enhancement for dual-purpose and HA
- Terraform state management per environment pattern
- Ansible group_vars and host_vars patterns

**Similar features to model after:**
- Elasticsearch cluster setup (multi-node with role separation)
- Kubernetes cluster deployment (multi-node with HA)
- Existing load balancer configuration (needs enhancement)

### Scope Boundaries

**In Scope:**

1. **Infrastructure Provisioning:**
   - Terraform module for two nginx-lb VMs
   - Static IP configuration for both nodes
   - VIP configuration for shared cluster IP

2. **HA Configuration:**
   - Corosync installation and configuration on both nodes
   - VIP failover setup
   - Health monitoring and automatic failover

3. **Load Balancer Configuration:**
   - Kubernetes API server load balancing (TCP passthrough to control plane nodes)
   - NodePort service load balancing (HTTP/HTTPS proxy to worker nodes)
   - Health checks for both backend types
   - Nginx configuration templates

4. **Kubeconfig Management:**
   - Ansible playbook to update kubeconfig on remote cluster nodes
   - Documentation for manual local kubeconfig updates
   - Backup and validation procedures

5. **Documentation:**
   - Deployment procedures
   - Configuration management
   - Troubleshooting guide
   - Failover testing procedures

**Out of Scope:**

1. **External Services:**
   - Load balancing for services outside the Kubernetes cluster
   - DNS-based load balancing or service discovery
   - Global server load balancing (GSLB)

2. **Advanced Features:**
   - WAF (Web Application Firewall) capabilities
   - DDoS protection
   - Rate limiting (beyond basic nginx capabilities)
   - Advanced monitoring/metrics collection (separate monitoring stack exists)

3. **SSL/TLS Management:**
   - Certificate generation or management (handled by existing step-certificates)
   - SSL/TLS termination at load balancer (passthrough mode only)

4. **Automatic Kubeconfig Updates:**
   - Automated local MacBook kubeconfig updates (manual only)
   - Dynamic kubeconfig injection for new clients

5. **Future Enhancements:**
   - Three-node HA cluster (two nodes sufficient for homelab)
   - Active-active load balancing (active-passive with VIP is sufficient)
   - Integration with external load balancer services
   - Automated scaling of load balancer capacity

### Technical Considerations

**Integration Points:**
- Proxmox API for VM provisioning
- HashiCorp Vault for credential retrieval
- Kubernetes API server endpoints (control plane nodes)
- Kubernetes NodePort services (worker nodes)
- Existing monitoring stack (Prometheus/Grafana)

**Existing System Constraints:**
- Network range: 192.168.10.0/24
- Storage backend: "tank" NFS share
- VM template: Ubuntu 25.04 cloud-init
- SSH key-based authentication required
- Vault integration mandatory for secrets

**Technology Preferences:**
- Corosync for HA (not keepalived) - based on user preference
- Nginx for load balancing
- Ansible for configuration management
- Terraform for infrastructure provisioning

**Similar Code Patterns to Follow:**
- Terraform: Use shared proxmox_vm module pattern
- Terraform: Separate environment with independent state file
- Terraform: Vault integration via data sources
- Ansible: Inventory group-based organization
- Ansible: Template-based configuration generation
- Ansible: Sequential playbook execution for cluster setup

### Success Criteria

**Infrastructure Deployment:**
- Two nginx-lb VMs successfully provisioned via Terraform
- VMs accessible via SSH with cloud-init configuration
- Static IPs configured correctly on both nodes
- VIP (192.168.10.250) accessible and responds

**HA Functionality:**
- Corosync cluster formed successfully between both nodes
- VIP automatically fails over when primary node is stopped
- VIP returns to primary when node is restored
- Both nodes maintain synchronized nginx configuration

**Load Balancer Functionality:**
- Kubernetes API accessible via VIP (192.168.10.250:6443)
- kubectl commands work through load balancer
- NodePort services accessible via load balancer standard ports
- Health checks properly detect backend failures
- Traffic distributes across backends using least_conn algorithm

**Configuration Management:**
- Ansible playbook successfully configures both nodes
- Nginx configuration deployed and validated
- Remote kubeconfig files updated to use VIP
- Local kubeconfig update instructions tested and validated

**Documentation:**
- Complete deployment guide available
- Troubleshooting procedures documented
- Failover testing procedures validated
- Manual kubeconfig update instructions clear and accurate

**Operational Validation:**
- Load balancer survives primary node failure
- No service interruption during failover
- All Kubernetes operations continue through load balancer
- NodePort services remain accessible during failover
- Monitoring shows healthy backend connections
