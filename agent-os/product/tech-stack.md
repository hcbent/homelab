# Tech Stack

This document defines the complete technical stack for the Homelab Infrastructure Platform, covering all layers from hypervisor to applications.

## Hypervisor & Virtualization

- **Hypervisor:** Proxmox VE (Virtual Environment)
- **VM Template:** Ubuntu 25.04 with cloud-init
- **Provisioning:** Terraform with telmate/proxmox provider
- **Node Configuration:** QEMU guest agent for VM management

## Infrastructure as Code

### Terraform
- **Version:** Latest stable (version constraints in versions.tf)
- **Providers:**
  - `telmate/proxmox` - Proxmox VM provisioning
  - `hashicorp/vault` v4.0+ - Secret management integration
- **State Management:** Local state files per environment (lab, kubernetes, home-apps, vault)
- **Module Structure:** Reusable proxmox_vm module for standardized VM creation

### Ansible
- **Version:** Latest stable
- **Collections:**
  - `community.hashi_vault` - Vault secret lookups
  - `kubernetes.core` - Kubernetes management
- **Inventory:** YAML-based with host groups (k8s_cp, k8s_worker, elasticsearch_nodes, elasticsearch_masters)
- **Authentication:** SSH key-based with vault integration for secrets

## Container Orchestration

### Kubernetes
- **Distribution:** K3s (lightweight Kubernetes)
- **Version:** Latest stable
- **Cluster Architecture:**
  - 3 control plane nodes (kube01-03)
  - 3 worker nodes (kube04-06)
- **Container Runtime:** containerd (embedded in K3s)
- **Network Plugin:** Flannel (default K3s CNI)

### GitOps & Continuous Deployment
- **GitOps Tool:** ArgoCD
- **Deployment Pattern:** Multi-source applications (Helm charts + values repository)
- **Sync Policy:** Automated with CreateNamespace support
- **Repository:** GitHub (git@github.com/wortmanb/homelab.git)

## Secret Management

### Vault Infrastructure
- **Secret Store:** HashiCorp Vault 1.18.3
- **Deployment:** Standalone VM (vault.lab.thewortmans.org)
- **Storage Backend:** File-based (raft for HA in future)
- **TLS:** Self-signed certificates (step-certificates internal CA)
- **Secret Engine:** KV v2 (versioned secrets)
- **Authentication Methods:**
  - Root token (initialization only)
  - Userpass (automation accounts)
  - Token-based (temporary access)

### Integration Points
- **Terraform:** Vault provider with data sources for secret retrieval
- **Ansible:** hashi_vault lookup plugin
- **Kubernetes:** external-secrets operator (future roadmap)

## Storage & Data Layer

### Network Storage
- **NAS Platform:** TrueNAS/FreeNAS
- **Protocols:**
  - iSCSI - Block storage for Kubernetes PVs
  - NFS - Shared filesystems and VM storage
- **Pool:** "tank" (primary storage pool)

### Kubernetes Storage
- **CSI Driver:** Democratic CSI
- **Storage Classes:**
  - `freenas-iscsi-csi` - Primary iSCSI volumes
  - `freenas-nfs-csi` - Shared NFS volumes
- **Volume Provisioning:** Dynamic with CSI provisioner

### Data Stores
- **Search & Analytics:** Elasticsearch 8.x (9-node cluster)
- **Time-Series Metrics:** Prometheus
- **Application Databases:** Per-application (PostgreSQL, MySQL as needed)

## Networking

### Infrastructure Networking
- **Network Range:** 192.168.10.0/24
- **Gateway:** 192.168.10.1
- **DNS Server:** 192.168.10.1 (internal) + Pi-hole
- **Domain:** lab.thewortmans.org (internal)

### Kubernetes Networking
- **CNI:** Flannel (default K3s)
- **Load Balancer:** MetalLB (bare metal LoadBalancer services)
- **Ingress Controller:** Traefik
- **Service Mesh:** None (Istio/Linkerd in roadmap)

### Certificate Management
- **Internal CA:** step-certificates
- **Certificate Manager:** cert-manager (roadmap)
- **TLS Termination:** Traefik ingress controller

## Observability & Monitoring

### Metrics & Monitoring
- **Metrics Collection:** Prometheus
- **Visualization:** Grafana
- **Alert Management:** AlertManager
- **Stack Deployment:** kube-prometheus-stack Helm chart v75.18.1

### Logging & Analytics
- **Log Aggregation:** Elasticsearch (9-node cluster)
- **Log Visualization:** Kibana
- **Log Shipping:** Fleet + Elastic Agent
- **Cluster Architecture:**
  - 6 data nodes (es01-es06)
  - 3 master nodes (es07-es09)

### Distributed Tracing
- **Current:** None
- **Roadmap:** Jaeger or Tempo

## Application Platform

### Media Management
- **Media Server:** Plex
- **Content Automation:**
  - Radarr (movies)
  - Sonarr (TV shows)
  - Lidarr (music)
- **Download Client:** qBittorrent
- **Indexer Manager:** Jackett

### Home Automation & Utilities
- **Home Automation:** Home Assistant
- **Network Services:** Pi-hole (DNS filtering and ad blocking)
- **Recipe Management:** Mealie
- **Document Management:** Paperless-ngx
- **Finance:** Actual Budget
- **File Sharing:** CopyParty

### AI/ML Services
- **LLM Inference:** Ollama (API-focused)
- **LLM UI:** Text Generation WebUI
- **GPU Support:** NVIDIA Tesla with nvidia.com/gpu resource allocation
- **Model Storage:** Persistent volumes for model caching

## Development & Operations

### Version Control
- **Platform:** GitHub
- **Repository Structure:**
  - `/tf` - Terraform configurations
  - `/ansible` - Ansible playbooks and roles
  - `/k8s` - Kubernetes manifests and ArgoCD apps
  - `/vault` - Vault setup and rotation scripts
  - `/docs` - Documentation

### Security & Compliance
- **Secret Scanning:** gitleaks
- **Git History Cleaning:** git-filter-repo
- **Pre-commit Hooks:** Secret detection, linting
- **Vault Audit:** Comprehensive audit logging (future)

### Deployment Automation
- **VM Provisioning:** Terraform apply workflows
- **Configuration:** Ansible playbooks (sequential for clusters)
- **Application Deployment:** ArgoCD automated sync
- **Helper Scripts:**
  - `add-vm.sh` - VM configuration generation
  - `setup_initial_cluster.sh` - K3s bootstrap
  - `add_node_to_cluster.sh` - Node joining
  - Vault scripts (initialize, unseal, configure, rotate)

### Testing & Validation
- **Current:** Manual validation
- **Roadmap:**
  - Terraform validation (terraform validate, tfsec)
  - Ansible testing (Molecule)
  - Kubernetes validation (kubeval, kube-score)
  - Infrastructure testing framework

## Deployment Environments

### Infrastructure Layers
1. **Hypervisor Layer:** Proxmox nodes (bare metal servers)
2. **VM Layer:** Terraform-provisioned Ubuntu VMs
3. **Configuration Layer:** Ansible-configured services and clusters
4. **Application Layer:** Kubernetes-orchestrated containerized applications

### Environment Separation
- **Terraform Environments:**
  - `tf/lab/` - Elasticsearch infrastructure
  - `tf/kubernetes/` - Kubernetes infrastructure
  - `tf/home-apps/` - Application infrastructure
  - `tf/vault/` - Vault server infrastructure
- **Kubernetes Namespaces:**
  - `argocd` - GitOps management
  - `prometheus` - Monitoring stack
  - `elastic-stack` - Logging infrastructure
  - `llm` - AI/ML services
  - `media` - Media management
  - `home-automation` - Home Assistant, Pi-hole
  - Per-application namespaces as needed

## Resource Allocation Standards

### VM Specifications
- **Kubernetes Control Plane:** 2 cores, 2GB RAM, 100GB storage
- **Kubernetes Workers:** 4 cores, 8GB RAM, 200GB storage
- **Elasticsearch Data Nodes:** 4 cores, 8GB RAM, 1TB storage
- **Elasticsearch Master Nodes:** 2 cores, 4GB RAM, 100GB storage
- **Plex Media Server:** 4 cores, 32GB RAM, high storage allocation
- **Vault Server:** 2 cores, 4GB RAM, 50GB storage

### Kubernetes Resource Management
- **LLM Workloads:** 8-16Gi memory, 1 GPU, persistent model storage
- **GPU Node Selection:** `nodeSelector: {accelerator: nvidia-tesla-gpu}`
- **GPU Tolerations:** Required for nvidia.com/gpu taint
- **Storage Classes:** Democratic CSI with dynamic provisioning

## Security Architecture

### Secret Management
- **Infrastructure Secrets:** Vault (Proxmox, TrueNAS, SSH keys)
- **Application Secrets:** Vault with Kubernetes secret injection (roadmap)
- **Ansible Vault:** Legacy/supplementary for Ansible-specific secrets

### Access Control
- **Vault Policies:**
  - `terraform` - Read infrastructure secrets
  - `ansible` - Read all homelab secrets
  - `apps` - Read application-specific secrets
  - `admin` - Full secret management
- **Kubernetes RBAC:** Service accounts with least-privilege (roadmap)
- **Network Policies:** Pod-to-pod communication controls (roadmap)

### Certificate & TLS
- **Internal Services:** step-certificates internal CA
- **External Services:** Let's Encrypt via cert-manager (roadmap)
- **Vault TLS:** Self-signed (VAULT_SKIP_VERIFY=true for dev)

## Backup & Disaster Recovery

### Current State
- **Vault Data:** Manual tar backup procedures documented
- **TrueNAS Data:** ZFS snapshots
- **Infrastructure Code:** Git version control

### Roadmap
- **Kubernetes Applications:** Velero backup operator
- **Elasticsearch Snapshots:** S3-compatible repository
- **Automated Testing:** Quarterly DR drills
- **Off-site Replication:** Secondary storage location

## Documentation Standards

### Repository Documentation
- **README.md:** Quick start and usage overview
- **DEPLOYMENT-GUIDE.md:** Step-by-step Vault deployment
- **SECURITY.md:** Security policies and secret management
- **CLAUDE.md:** AI assistant guidance files
- **README-VAULT.md:** Terraform and Ansible Vault integration

### Code Documentation
- **Terraform:** Variable descriptions, output documentation
- **Ansible:** Playbook headers, role documentation
- **Kubernetes:** ArgoCD app annotations, inline comments

## Future Technology Additions

Based on roadmap priorities:
- **Service Mesh:** Istio or Linkerd for advanced traffic management
- **Backup Operator:** Velero for Kubernetes application backups
- **External Secrets:** external-secrets operator for Vault integration
- **Dependency Automation:** Renovate for automated dependency updates
- **Infrastructure Testing:** Terratest, Molecule, compliance scanning
- **Multi-Cluster:** Federation, centralized management plane
- **Auto-Scaling:** Horizontal Pod Autoscaler, cluster autoscaler
