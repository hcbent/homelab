# Spec Requirements: Kubespray K8s Cluster Deployment

## Initial Description
Implement automated Kubernetes cluster deployment using kubespray as an alternative to the current K3s setup. This will enable production-grade Kubernetes clusters with full customization capabilities while integrating with the existing homelab infrastructure automation pipeline.

Deploy Kubernetes clusters using kubespray (already installed at ~/git/kubespray) to provide:
- Production-grade Kubernetes features and flexibility
- Full control over cluster components (CNI, storage, ingress, etc.)
- Better support for cluster upgrades and maintenance
- Integration with existing Proxmox/Terraform/Ansible infrastructure
- Coexistence or migration path from current K3s setup

## Requirements Discussion

### First Round Questions

**Q1: VM Provisioning Approach**
**Question:** Should we create new Terraform modules to provision VMs for the kubespray cluster, or use existing VMs? If new, what specifications (CPU cores, RAM, storage) should the control plane and worker nodes have?
**Answer:** Create new Terraform modules to provision VMs. User has existing VMs but wants proper tooling for infrastructure management.

**Q2: Node Configuration**
**Question:** How many control plane nodes and worker nodes should the cluster have? Should we follow the existing K3s pattern (3 control plane + 3 workers) or a different configuration?
**Answer:**
- Control plane nodes: km01-km03 (2-3 nodes total)
  - IMPORTANT: km01 is NOT a VM - it's bare metal
  - km02 and km03 are VMs to be provisioned via Terraform
- Worker nodes: kube01-kube03 (3 worker nodes initially)
- Naming convention: Masters use km01-km99, workers use kube01-kube99
- CRITICAL REQUIREMENT: Ensure etcd is distributed across all control plane nodes for HA

**Q3: CNI Plugin Selection**
**Question:** Which CNI plugin should kubespray deploy? Options include Calico (most common), Cilium (advanced features), Flannel (simple), or others?
**Answer:** Use whatever is easiest for a novice K8s admin to manage. Recommendation: Calico or Flannel for simplicity.

**Q4: Storage Integration**
**Question:** Should we integrate Democratic CSI with FreeNAS iSCSI/NFS backends (matching existing setup), or configure different storage options?
**Answer:** YES - Use Democratic CSI for ALL persistent volumes with FreeNAS iSCSI/NFS backend (matching existing infrastructure).

**Q5: Load Balancing and Ingress**
**Question:** Should the cluster include MetalLB for LoadBalancer services and Traefik for ingress (matching existing K3s setup)?
**Answer:**
- YES - Include MetalLB for LoadBalancer services
- YES - Include Traefik for ingress
- Deploy ArgoCD first if that makes deployment of other components easier

**Q6: Ansible Workflow Integration**
**Question:** Should we create wrapper playbooks in the ansible/ directory that call kubespray, or maintain a separate kubespray workflow?
**Answer:** Option A - Create wrapper playbooks in ansible/ directory that call kubespray. This maintains consistency with existing automation patterns.

**Q7: Vault Integration**
**Question:** Should the deployment retrieve credentials and secrets from Vault during provisioning, or handle secrets separately?
**Answer:**
- YES - Retrieve credentials from Vault during provisioning
- Integrate with Vault as early as possible for all secrets management
- Follow existing Vault integration patterns from current infrastructure

**Q8: ArgoCD Bootstrap**
**Question:** Should ArgoCD bootstrapping be automated as part of the deployment workflow, or handled separately after cluster creation?
**Answer:** Automate ArgoCD bootstrapping as part of deployment workflow. This enables GitOps-based management of all subsequent components.

**Q9: Kubespray Configuration Location**
**Question:** Where should kubespray configuration files (inventory, group_vars, host_vars) be stored - in the homelab repo or kept separate?
**Answer:** Put all kubespray configuration under kubespray/ directory in homelab repo. This centralizes all infrastructure-as-code in one repository.

**Q10: Cluster Components**
**Question:** Which cluster components should be deployed: DNS (CoreDNS), metrics-server, certificate management (cert-manager), monitoring (Prometheus), container runtime selection (containerd/cri-o)?
**Answer:** Deploy everything necessary for fully operational platform:
- DNS (CoreDNS) - YES
- Certificate management (cert-manager) - YES
- Container runtime (containerd) - YES
- Skip Prometheus for initial deployment (can add later via ArgoCD)

**Q11: Documentation Scope**
**Question:** What documentation should be created: deployment procedures only, or also upgrade workflows, backup/restore, troubleshooting?
**Answer:** Document ALL of these:
- Initial cluster deployment
- Adding/removing nodes
- Cluster upgrades
- Backup/restore procedures
- Troubleshooting common issues
- Disaster recovery

**Q12: Migration Strategy**
**Question:** Should we plan for coexistence with K3s cluster, migration timeline, or eventual replacement?
**Answer:** Explicitly NOT included: Multi-cluster management (user will only ever have one cluster). Focus on single production-grade kubespray cluster.

### Existing Code to Reference

**Similar Features Identified:**

**Terraform Patterns:**
- Location: `tf/` directory
- Reference for: VM provisioning module structure, variable definitions, tfvars patterns
- Existing module: `tf/modules/proxmox_vm/` - Reusable module for Proxmox VM provisioning

**Ansible Playbook Structure:**
- Location: `ansible/playbooks/` directory
- Reference for: Sequential playbook patterns, role organization, task structure
- Key examples:
  - `00_setup_host.yml` - Base host configuration pattern
  - `01_setup_k8s.yml` - K8s prerequisites pattern
  - `02_setup_first_cp_node.yml` - Control plane initialization
  - `02_setup_other_cp_nodes.yml` - Additional control plane nodes
  - `02_setup_worker.yml` - Worker node configuration

**Ansible Inventory Organization:**
- Location: `ansible/inventory/` directory
- Reference for: Inventory file structure, group organization, host variable patterns
- Contains: Multiple environment inventories (lab, monitoring, cchs, deepfreeze, home)

**Vault Integration Examples:**
- Location: `ansible/` directory
- Files: `.vault_pass`, `SECRET_MANAGEMENT.md`
- Reference for: Vault authentication, secret retrieval patterns

**Existing K3s Configuration:**
- Control plane naming: kube01-03
- Worker naming: kube04-06
- Can reference for cluster sizing patterns

### Follow-up Questions

**Follow-up 1: Bare Metal Control Plane Node**
**Question:** Can you provide details about the bare metal control plane node (km01):
- Is it already available and configured?
- What are its specifications (CPU cores, RAM, storage)?
- What OS is installed (Ubuntu, Debian, Rocky Linux)?
- Does it need any special configuration compared to VM nodes?

**Answer:**
- Status: Already configured and available
- Hostname: km01.lab.thewortmans.org
- IP Address: 192.168.10.234
- Type: NOT a VM (bare metal hardware)
- Specifications:
  - CPU: 4 cores
  - RAM: 16GB
  - Storage: 1TB

**Follow-up 2: VM Specifications**
**Question:** What specifications should the Terraform modules use for provisioning VMs:
- Control plane VMs (km02, km03): How many CPU cores, RAM, disk space?
- Worker VMs (kube01-kube03): How many CPU cores, RAM, disk space?
- Should these match existing K3s node specs or be different?

**Answer:**
- Use best practices for small Kubernetes clusters
- Operating System: Ubuntu 25.04 for all VMs
- Control plane VMs (km02, km03): Follow Kubernetes best practices
- Worker VMs (kube01-kube03): Follow Kubernetes best practices
- Scalability: User can add more nodes in the future

**Recommended VM Specifications (based on K8s best practices):**

Control Plane Nodes (km02, km03):
- CPU Cores: 4 cores (minimum 2, recommended 4 for production)
- RAM: 8GB (minimum 4GB, recommended 8GB for production)
- Disk: 100GB (50-100GB range typical)
- Network: 1Gbps network interface
- Rationale: Control plane runs API server, scheduler, controller-manager, and etcd

Worker Nodes (kube01-kube03):
- CPU Cores: 4-8 cores (scalable based on workload)
- RAM: 8-16GB (scalable based on workload)
- Disk: 200GB (100-500GB depending on local storage needs)
- Network: 1Gbps network interface
- Rationale: Workers run application pods and require resources for workloads

Note: These specifications allow for growth and can be adjusted in the Terraform configuration.

**Follow-up 3: MetalLB IP Range**
**Question:** What IP address range should MetalLB use for LoadBalancer services? Should this:
- Match existing K3s MetalLB configuration?
- Use a new dedicated range?
- What is the specific CIDR or IP range?

**Answer:**
- Use MetalLB's default range if one exists
- Otherwise use: 192.168.100.0/24
- Note: Existing configuration shows 192.168.10.50-192.168.10.99 range
- Recommendation: Use 192.168.100.0/24 as specified by user, or discuss using existing 192.168.10.50-99 range

**Follow-up 4: FreeNAS Connection Details**
**Question:** For Democratic CSI integration with FreeNAS:
- Are FreeNAS connection details (IP, credentials, iSCSI target info) already stored in Vault?
- If yes, what are the Vault secret paths?
- If no, where should these credentials be stored?

**Answer:**
- Credentials should already be in Vault
- Refer to project documentation for Vault secret paths

**Vault Secret Paths (from codebase research):**
```
Vault Server: https://192.168.10.101:8200

FreeNAS/TrueNAS Secrets:
- Path: secret/homelab/freenas/credentials
  - api_key: TrueNAS API key
  - root_password: Root password
- Path: secret/homelab/freenas/ssh
  - private_key: SSH private key
  - public_key: SSH public key

Example usage in Democratic CSI:
- Secret path: secret/data/homelab/freenas (KV v2 format)
- Keys: api-key, password, ssh-private-key
```

**Follow-up 5: Certificate Management Strategy**
**Question:** For cert-manager and TLS certificates:
- Should we use Let's Encrypt for public-facing services?
- Internal CA for cluster-internal certificates?
- Are there existing CA certificates or should we generate new ones?
- Is there an existing step-certificates installation to integrate with?

**Answer:**
- Internal CA: Use cert-manager for cluster-internal certificates
- Public-facing services: Will use NGINX Proxy Manager (in front of cluster)
- NGINX Proxy Manager handles: Let's Encrypt certificates
- Cluster responsibility: Does NOT need to manage public Let's Encrypt certs directly
- Strategy: Internal CA for internal services, external proxy for public services

**Follow-up 6: Proxmox Connection Details**
**Question:** For Terraform VM provisioning on Proxmox:
- Are Proxmox API credentials already in Vault?
- What is the Proxmox host/cluster name?
- Which storage pool should VMs use?
- Which network bridge should VMs connect to?

**Answer:**
- Credentials should already be in Vault
- Refer to project documentation for details

**Proxmox Configuration (from codebase research):**
```
Vault Secret Paths:
- Path: secret/homelab/proxmox/terraform
  - username: Proxmox API username (e.g., terraform@pve)
  - password: Proxmox API password

Proxmox Infrastructure:
- API URL: https://pve1.lab.thewortmans.org:8006/api2/json
- Proxmox Nodes: pve1, pve2, pve3 (3-node cluster)
- Storage Pool: "tank" (NFS storage backend)
- Network Bridge: vmbr0
- Network: 192.168.10.0/24
- Gateway: 192.168.10.1
- DNS: 192.168.10.1
- Domain: lab.thewortmans.org
- Template: ubuntu-25.04 (cloud-init template)
- TLS: Self-signed certificates (skip_tls_verify = true)

VM ID Ranges (from existing infrastructure):
- Elasticsearch: 301-309 (es01-es09)
- Kubernetes K3s: 201-206 (kube01-kube06)
- Home apps: 101+ (plex, etc.)
- Suggested for kubespray: 221-226 (km02, km03, kube01-kube03)
  - km02: 221 (control plane)
  - km03: 222 (control plane)
  - kube01: 223 (worker)
  - kube02: 224 (worker)
  - kube03: 225 (worker)
```

## Visual Assets

### Files Provided:
No visual assets provided.

### Visual Insights:
N/A - No visual files were found in the visuals folder.

## Requirements Summary

### Functional Requirements

**Infrastructure Provisioning:**
- Create Terraform modules for VM provisioning (km02, km03, kube01-kube03)
- Support for bare metal node (km01) alongside VM nodes
- Integration with Proxmox hypervisor via Terraform
- Dynamic inventory generation from Terraform outputs
- VM specifications following Kubernetes best practices for small clusters

**Cluster Deployment:**
- Deploy production-grade Kubernetes using kubespray
- 3 control plane nodes total (1 bare metal km01 + 2 VMs km02-km03) with distributed etcd
- 3 worker nodes (kube01-kube03) initially, scalable in future
- Novice-friendly CNI plugin (Calico or Flannel)
- Containerd container runtime
- Ubuntu 25.04 operating system for all VMs

**Storage and Networking:**
- Democratic CSI for persistent volumes (FreeNAS iSCSI/NFS backend)
- MetalLB for LoadBalancer service type (IP range: 192.168.100.0/24 or 192.168.10.50-99)
- Traefik ingress controller
- CoreDNS for cluster DNS
- Network: 192.168.10.0/24 with gateway 192.168.10.1

**Security and Secrets:**
- HashiCorp Vault integration for all secrets (server: https://192.168.10.101:8200)
- Retrieve credentials from Vault during provisioning
- Cert-manager for internal certificate management
- Secure etcd configuration across control plane nodes
- External NGINX Proxy Manager for public-facing TLS (Let's Encrypt)

**GitOps and Automation:**
- Automated ArgoCD bootstrap post-deployment
- ArgoCD-based deployment of additional components
- Wrapper Ansible playbooks calling kubespray
- Integration with existing ansible/ directory structure
- Kubespray configuration stored in homelab repo under kubespray/ directory

**Operational Capabilities:**
- Node addition/removal procedures
- Cluster upgrade workflows
- Backup and restore functionality
- Disaster recovery procedures

### Reusability Opportunities

**Terraform Modules:**
- Reference existing VM provisioning patterns in `tf/` directory
- Reuse `tf/modules/proxmox_vm/` module for VM creation
- Follow variable structure and tfvars patterns from `tf/lab/` and `tf/kubernetes/`
- Leverage existing Proxmox provider configuration with Vault integration

**Ansible Playbooks:**
- Model wrapper playbooks after existing sequential K8s setup playbooks
- Reuse role structure from `ansible/roles/` directory
- Follow existing playbook organization patterns from `ansible/playbooks/`

**Inventory Management:**
- Reference inventory structure from `ansible/inventory/` directory
- Adopt existing group_vars and host_vars patterns
- Maintain consistency with current inventory organization

**Vault Integration:**
- Follow existing Vault authentication patterns (token-based initially)
- Reference `docs/VAULT-SETUP.md` for best practices
- Use established secret paths: `secret/homelab/proxmox/terraform` and `secret/homelab/freenas/credentials`
- Reuse vault authentication from existing Terraform providers

**Component Deployment:**
- Democratic CSI configuration can reference `k8s/helm/values/democratic-csi-defaults.yaml`
- MetalLB configuration from `k8s/basement/metallb-ippool.yaml`
- Traefik configuration can reference existing ingress patterns
- ArgoCD bootstrap can follow existing GitOps patterns

**Existing Infrastructure Patterns:**
- Proxmox VM module with cloud-init, SSH keys, prevent_destroy lifecycle
- Storage on "tank" NFS backend
- Network on vmbr0 bridge
- Ubuntu 25.04 template cloning
- Static IP configuration via cloud-init (ipconfig0)

### Scope Boundaries

**In Scope:**
- Kubespray inventory configuration for homelab nodes (1 bare metal + 5 VMs)
- Terraform modules for VM provisioning (km02, km03, kube01-kube03)
- Bare metal node (km01) integration into kubespray inventory
- Ansible wrapper playbooks calling kubespray from `ansible/` directory
- Kubespray cluster customization (group_vars, host_vars)
- CNI plugin configuration (Calico or Flannel)
- Democratic CSI storage integration with FreeNAS backend
- MetalLB LoadBalancer configuration (192.168.100.0/24 range)
- Traefik ingress controller setup
- Cert-manager certificate management (internal CA only)
- Vault integration for secrets retrieval (Proxmox, FreeNAS credentials)
- ArgoCD bootstrap automation
- CoreDNS configuration
- Distributed etcd setup across 3 control plane nodes
- Comprehensive documentation:
  - Initial cluster deployment procedures
  - Node addition/removal workflows
  - Cluster upgrade procedures
  - Backup and restore procedures
  - Troubleshooting guides
  - Disaster recovery runbooks

**Out of Scope:**
- Multi-cluster management (user will only have one cluster)
- Actual migration of production workloads from K3s
- Replacement/removal of existing K3s cluster during initial deployment
- Prometheus monitoring stack (added later via ArgoCD)
- New application deployments (focus on cluster foundation)
- Major infrastructure changes beyond K8s deployment method
- GPU node configuration (not mentioned in requirements)
- Elasticsearch cluster integration (separate from K8s cluster)
- Let's Encrypt certificate management (handled by external NGINX Proxy Manager)
- Public-facing ingress routing (handled by external proxy)

### Technical Considerations

**Infrastructure Layer:**
- Terraform must handle mixed infrastructure (1 bare metal + 5 VMs)
- Proxmox API integration for VM lifecycle management
- Proxmox cluster: 3 nodes (pve1, pve2, pve3) for HA VM distribution
- Dynamic inventory generation for kubespray consumption
- VM specifications:
  - Control plane VMs: 4 cores, 8GB RAM, 100GB disk
  - Worker VMs: 4-8 cores, 8-16GB RAM, 200GB disk
  - Bare metal km01: 4 cores, 16GB RAM, 1TB storage
- Cloud-init for VM initialization with SSH keys
- Static IP assignment via cloud-init (ipconfig0)

**Network Architecture:**
- Network: 192.168.10.0/24
- Gateway: 192.168.10.1
- DNS: 192.168.10.1
- Domain: lab.thewortmans.org
- Bare metal km01: 192.168.10.234
- VM IPs: Assign static IPs in 192.168.10.x range
- MetalLB IP pool: 192.168.100.0/24 or existing 192.168.10.50-99
- Network bridge: vmbr0 on all Proxmox nodes
- CNI plugin must support homelab network topology
- Ingress routing strategy: Internal Traefik + External NGINX Proxy Manager

**Storage Integration:**
- Democratic CSI driver installation and configuration
- FreeNAS backend: "tank" NFS storage
- FreeNAS API credentials from Vault: `secret/homelab/freenas/credentials`
- Storage class definitions for iSCSI and NFS
- iSCSI path: /etc/iscsi on all nodes
- PV/PVC management and provisioning

**High Availability:**
- Etcd distributed across 3 control plane nodes (km01, km02, km03)
- Minimum 3 nodes for etcd quorum
- Control plane component redundancy
- Load balancing for API server access
- Backup strategy for etcd data

**Security and Secrets:**
- Vault as single source of truth (https://192.168.10.101:8200)
- Vault secret paths:
  - Proxmox: `secret/homelab/proxmox/terraform` (username, password)
  - FreeNAS: `secret/homelab/freenas/credentials` (api_key, root_password)
  - FreeNAS SSH: `secret/homelab/freenas/ssh` (private_key, public_key)
- Secure credential retrieval during provisioning
- Certificate strategy: Internal CA via cert-manager, external Let's Encrypt via NGINX Proxy Manager
- RBAC configuration for cluster access
- Network policies for workload isolation
- Self-signed TLS for internal Vault/Proxmox communication

**Automation and GitOps:**
- Ansible playbook sequencing for repeatable deployments
- Kubespray version pinning for reproducibility
- Kubespray location: ~/git/kubespray
- Kubespray config location: homelab repo under `kubespray/` directory
- ArgoCD bootstrap enabling declarative cluster configuration
- Git repository structure for kubespray configuration
- Wrapper playbooks integrate with existing `ansible/` structure

**Existing Infrastructure Compatibility:**
- Integration with current Vault setup at 192.168.10.101
- Compatibility with existing DNS and network infrastructure
- Potential coexistence with K3s cluster (at least initially)
- Reuse of existing storage backend (FreeNAS "tank")
- Same domain namespace (lab.thewortmans.org)
- Same cloud-init user (bret) with SSH key authentication

**Operational Requirements:**
- Node addition must not disrupt running workloads
- Upgrade procedures must support rolling updates
- Backup and restore must be tested and documented
- Disaster recovery procedures must be comprehensive
- Troubleshooting guides must cover common issues for novice K8s admins
- Support for future node scaling (beyond initial 3 workers)

**Technology Stack:**
- Kubespray (already installed at ~/git/kubespray)
- Terraform for infrastructure provisioning
- Ansible for configuration management
- Proxmox as virtualization platform (3-node cluster)
- HashiCorp Vault for secrets management (192.168.10.101)
- FreeNAS for storage backend ("tank" pool)
- ArgoCD for GitOps
- Containerd as container runtime
- Calico or Flannel for CNI
- MetalLB for LoadBalancer services
- Traefik for ingress
- Cert-manager for certificate management (internal)
- CoreDNS for cluster DNS
- Ubuntu 25.04 as base OS for all VMs

### Infrastructure Specifications Summary

**Bare Metal Control Plane Node:**
- Hostname: km01.lab.thewortmans.org
- IP: 192.168.10.234
- Specs: 4 cores, 16GB RAM, 1TB storage
- Status: Already configured and available

**VM Control Plane Nodes (to be provisioned):**
- km02: VMID 221, 4 cores, 8GB RAM, 100GB disk
- km03: VMID 222, 4 cores, 8GB RAM, 100GB disk
- OS: Ubuntu 25.04 (cloned from template)
- Storage: tank (NFS)
- Network: vmbr0 bridge

**VM Worker Nodes (to be provisioned):**
- kube01: VMID 223, 4-8 cores, 8-16GB RAM, 200GB disk
- kube02: VMID 224, 4-8 cores, 8-16GB RAM, 200GB disk
- kube03: VMID 225, 4-8 cores, 8-16GB RAM, 200GB disk
- OS: Ubuntu 25.04 (cloned from template)
- Storage: tank (NFS)
- Network: vmbr0 bridge

**Proxmox Infrastructure:**
- Nodes: pve1, pve2, pve3
- API: https://pve1.lab.thewortmans.org:8006/api2/json
- Credentials: From Vault `secret/homelab/proxmox/terraform`
- Storage: tank (NFS)
- Network: vmbr0
- Template: ubuntu-25.04

**Network Configuration:**
- Network: 192.168.10.0/24
- Gateway: 192.168.10.1
- DNS: 192.168.10.1
- Domain: lab.thewortmans.org
- MetalLB Range: 192.168.100.0/24 (or 192.168.10.50-99)

**Vault Configuration:**
- Server: https://192.168.10.101:8200
- Secrets Engine: KV v2 at `secret/`
- Required Secrets:
  - `secret/homelab/proxmox/terraform` (username, password)
  - `secret/homelab/freenas/credentials` (api_key, root_password)
  - `secret/homelab/freenas/ssh` (private_key, public_key)

**FreeNAS Storage:**
- Backend: Democratic CSI
- Pool: tank
- Protocols: iSCSI and NFS
- Credentials: From Vault `secret/homelab/freenas/credentials`
