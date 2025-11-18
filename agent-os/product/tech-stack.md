# Tech Stack

This document defines the complete technical stack for the Homelab Tailscale Migration project, covering all layers from hypervisor to applications, including new Tailscale networking components.

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
- **Key Path:** /Users/bret/.ssh/github_rsa (per user preference)

## Container Orchestration

### Kubernetes
- **Distribution:** K3s (lightweight Kubernetes)
- **Version:** Latest stable
- **Cluster Architecture:**
  - 3 control plane nodes (km01, km02, km03)
  - Worker nodes as needed
- **Container Runtime:** containerd (embedded in K3s)
- **Network Plugin:** Flannel (default K3s CNI)
- **Service Type Preference:** NodePort (per user standards)

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
- **Tailscale:** Auth keys stored at `secret/tailscale/auth-keys`

## Networking

### VPN & Zero-Trust Mesh (NEW - Tailscale Migration)

#### Tailscale Core Components
- **VPN Technology:** WireGuard-based mesh network
- **Tailscale Deployment:** Kubernetes operator or DaemonSet
- **Node Coverage:** All Kubernetes nodes (km01, km02, km03)
- **Client Support:** macOS, iOS, Android, Linux, Windows
- **Mesh Architecture:** Peer-to-peer with NAT traversal, no central VPN server

#### Tailscale Features
- **MagicDNS:** Automatic DNS resolution for all tailnet devices
  - Node hostnames: `<nodename>.tail-xxxxx.ts.net`
  - Custom domain: `*.home.lab` for services
- **Tailscale Funnel:** HTTPS ingress for public service exposure
  - Permanent Funnel: kibana.bwortman.us
  - Permanent Funnel: cchs.makerspace.hcbent.com
  - On-demand Funnel: Any service for temporary sharing
- **ACL Policies:** Centralized access control per user and device
- **Audit Logging:** Comprehensive logs of all connection attempts
- **Certificate Management:** Automatic HTTPS certificates for Funnel endpoints

#### Tailscale Integration
- **Helm Chart:** Official Tailscale operator chart (or community chart)
- **Auth Key Source:** HashiCorp Vault (`secret/tailscale/auth-keys`)
- **Secret Management:** Kubernetes Secret populated from Vault
- **Monitoring:** Prometheus metrics export (if available)
- **GitOps:** Managed via ArgoCD application

### Infrastructure Networking
- **Network Range:** 192.168.10.0/24
- **Gateway:** 192.168.10.1
- **DNS Server:** 192.168.10.1 (internal) + Pi-hole
- **Internal Domain:** lab.thewortmans.org
- **Tailscale Domain:** home.lab (for service access)

### Kubernetes Networking
- **CNI:** Flannel (default K3s)
- **Load Balancer:** MetalLB (bare metal LoadBalancer services)
- **Ingress Controller (Legacy):** Traefik - being replaced by Tailscale + NGINX
- **Internal Proxy (NEW):** NGINX for clean URL routing within Tailscale mesh
- **Service Mesh:** None (Istio/Linkerd in future roadmap)

### Reverse Proxy Architecture

#### Current (Pre-Migration)
- **External Proxy:** NGINX Proxy Manager
- **DNS Provider:** Cloudflare
- **Port Forwarding:** Multiple ports (443, various service ports)
- **TLS Termination:** NGINX Proxy Manager with Let's Encrypt

#### Target (Post-Migration)
- **Internal Proxy:** Standard NGINX deployed in Kubernetes
  - Deployment: NodePort service
  - Configuration: ConfigMap-based
  - Routing: Hostname-based (service.home.lab)
  - Health Checks: Upstream monitoring
- **External Access:** Tailscale Funnel (public services only)
- **DNS Provider:** Tailscale MagicDNS (internal), Cloudflare (public Funnel endpoints)
- **Port Forwarding:** None - all access via Tailscale mesh
- **TLS Management:** Tailscale Funnel automatic certificates

### Certificate Management
- **Internal CA:** step-certificates
- **Internal Services:** Self-signed via step-certificates
- **Public Services (Funnel):** Automatic Tailscale-provided HTTPS certificates
- **Certificate Manager:** cert-manager (future roadmap for other use cases)

## Storage & Data Layer

### Network Storage
- **NAS Platform:** TrueNAS/FreeNAS
- **Protocols:**
  - iSCSI - Block storage for Kubernetes PVs
  - NFS - Shared filesystems and VM storage
- **Pool:** "tank" (primary storage pool - per user standards)

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

### Tailscale-Specific Monitoring (NEW)
- **Connection Metrics:** Tailscale node connectivity status
- **Funnel Availability:** Public service endpoint monitoring
- **MagicDNS Health:** DNS resolution success rate
- **Metrics Export:** Prometheus exporter (if available) or custom metrics
- **Dashboards:** Grafana dashboards for Tailscale mesh health
- **Alerts:** Node disconnection, Funnel downtime, DNS failures

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
- **Access Method (Post-Migration):** Tailscale mesh via service.home.lab URLs

### Home Automation & Utilities
- **Home Automation:** Home Assistant
- **Network Services:** Pi-hole (DNS filtering and ad blocking)
- **Recipe Management:** Mealie
- **Document Management:** Paperless-ngx
- **Finance:** Actual Budget
- **File Sharing:** CopyParty
- **Access Method (Post-Migration):** Tailscale mesh via service.home.lab URLs

### AI/ML Services
- **LLM Inference:** Ollama (API-focused)
- **LLM UI:** Text Generation WebUI
- **GPU Support:** NVIDIA Tesla with nvidia.com/gpu resource allocation
- **Model Storage:** Persistent volumes for model caching

### Public-Facing Services (Tailscale Funnel)
- **kibana.bwortman.us:** Elasticsearch/Kibana analytics dashboard
  - Access: Public via Tailscale Funnel
  - TLS: Automatic Tailscale certificate
  - Purpose: Log analysis and visualization
- **cchs.makerspace.hcbent.com:** CCHS Makerspace application
  - Access: Public via Tailscale Funnel
  - TLS: Automatic Tailscale certificate
  - Purpose: Community makerspace management

## Development & Operations

### Version Control
- **Platform:** GitHub
- **Repository Structure:**
  - `/tf` - Terraform configurations
  - `/ansible` - Ansible playbooks and roles
  - `/k8s` - Kubernetes manifests and ArgoCD apps
  - `/vault` - Vault setup and rotation scripts
  - `/docs` - Documentation
  - `/tailscale` (NEW) - Tailscale deployment configs, ACL policies, runbooks

### Security & Compliance
- **Secret Scanning:** gitleaks
- **Git History Cleaning:** git-filter-repo
- **Pre-commit Hooks:** Secret detection, linting
- **Vault Audit:** Comprehensive audit logging (future)
- **Tailscale Audit:** Connection and access logging

### Deployment Automation
- **VM Provisioning:** Terraform apply workflows
- **Configuration:** Ansible playbooks (sequential for clusters)
- **Application Deployment:** ArgoCD automated sync
- **Helper Scripts:**
  - `add-vm.sh` - VM configuration generation
  - `setup_initial_cluster.sh` - K3s bootstrap
  - `add_node_to_cluster.sh` - Node joining
  - Vault scripts (initialize, unseal, configure, rotate)
  - Tailscale scripts (NEW - Funnel enable/disable, ACL updates)

### Testing & Validation
- **Current:** Manual validation
- **Roadmap:**
  - Terraform validation (terraform validate, tfsec)
  - Ansible testing (Molecule)
  - Kubernetes validation (kubeval, kube-score)
  - Infrastructure testing framework
  - Tailscale connectivity testing (mesh validation, DNS resolution checks)

## Deployment Environments

### Infrastructure Layers
1. **Hypervisor Layer:** Proxmox nodes (bare metal servers)
2. **VM Layer:** Terraform-provisioned Ubuntu VMs
3. **Configuration Layer:** Ansible-configured services and clusters
4. **Application Layer:** Kubernetes-orchestrated containerized applications
5. **Networking Layer (NEW):** Tailscale mesh overlay for secure access

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
  - `tailscale` (NEW) - Tailscale operator/DaemonSet
  - `networking` (NEW) - Internal NGINX proxy
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
- **Service Types:** NodePort preferred (per user standards)

### Tailscale Resource Requirements (NEW)
- **Tailscale Operator/DaemonSet:**
  - CPU: 100m request, 200m limit
  - Memory: 128Mi request, 256Mi limit
  - Per-node deployment (3 nodes = 3 pods)
- **Internal NGINX Proxy:**
  - CPU: 200m request, 500m limit
  - Memory: 256Mi request, 512Mi limit
  - Replicas: 2 for high availability
  - Service Type: NodePort

## Security Architecture

### Secret Management
- **Infrastructure Secrets:** Vault (Proxmox, TrueNAS, SSH keys)
- **Application Secrets:** Vault with Kubernetes secret injection (roadmap)
- **Tailscale Secrets:** Vault (`secret/tailscale/auth-keys`)
- **Ansible Vault:** Legacy/supplementary for Ansible-specific secrets

### Access Control

#### Vault Policies
- `terraform` - Read infrastructure secrets
- `ansible` - Read all homelab secrets
- `apps` - Read application-specific secrets
- `tailscale` - Read Tailscale auth keys
- `admin` - Full secret management

#### Kubernetes RBAC
- **Current:** Basic service accounts
- **Roadmap:** Least-privilege service accounts per namespace
- **Tailscale:** Dedicated service account for operator/DaemonSet

#### Tailscale ACL Policies (NEW)
- **User-Based Access:** Per-user permissions for services
- **Device Tagging:** Tag-based access control (e.g., tag:k8s, tag:laptop)
- **Service Isolation:** Granular ACLs per service or namespace
- **Default Deny:** Explicit allow required for all access
- **Audit Logging:** All connection attempts logged

### Network Security

#### Pre-Migration
- Port forwarding rules on external firewall
- NGINX Proxy Manager authentication
- Cloudflare DDoS protection
- Limited access control granularity

#### Post-Migration
- **Zero Port Forwarding:** All access via Tailscale mesh
- **Encrypted Mesh:** WireGuard encryption for all connections
- **Zero-Trust:** Every connection authenticated and authorized
- **Minimal Public Exposure:** Only 2 services via Tailscale Funnel
- **No External Dependencies:** Direct peer-to-peer connectivity
- **ACL-Based Security:** Centralized, auditable access control

### Certificate & TLS
- **Internal Services:** step-certificates internal CA
- **Tailscale Funnel:** Automatic Tailscale-provided HTTPS certificates
- **External Services (Future):** Let's Encrypt via cert-manager (roadmap)
- **Vault TLS:** Self-signed (VAULT_SKIP_VERIFY=true for dev)

## Backup & Disaster Recovery

### Current State
- **Vault Data:** Manual tar backup procedures documented
- **TrueNAS Data:** ZFS snapshots
- **Infrastructure Code:** Git version control
- **Tailscale Configuration:** ACL policies version-controlled in git

### Roadmap
- **Kubernetes Applications:** Velero backup operator
- **Elasticsearch Snapshots:** S3-compatible repository
- **Automated Testing:** Quarterly DR drills
- **Off-site Replication:** Secondary storage location
- **Tailscale Restore:** Auth key rotation and node re-registration procedures

## Documentation Standards

### Repository Documentation
- **README.md:** Quick start and usage overview
- **DEPLOYMENT-GUIDE.md:** Step-by-step Vault deployment
- **SECURITY.md:** Security policies and secret management
- **CLAUDE.md:** AI assistant guidance files (per user preference)
- **README-VAULT.md:** Terraform and Ansible Vault integration
- **TAILSCALE-MIGRATION.md (NEW):** Comprehensive Tailscale migration guide
- **SERVICE-CATALOG.md (NEW):** All services with Tailscale URLs

### Code Documentation
- **Terraform:** Variable descriptions, output documentation
- **Ansible:** Playbook headers, role documentation
- **Kubernetes:** ArgoCD app annotations, inline comments
- **Tailscale:** ACL policy comments, Funnel configuration notes

### Operational Runbooks (NEW - Tailscale)
- **Connection Troubleshooting:** DNS resolution, mesh connectivity issues
- **Funnel Management:** Enable/disable procedures, certificate renewal
- **ACL Updates:** Adding users, modifying permissions, testing changes
- **Node Management:** Adding Kubernetes nodes to tailnet, removing devices
- **Auth Key Rotation:** Generating new keys, updating Vault, redeploying
- **Rollback Procedures:** Complete step-by-step rollback to previous architecture

## Migration Strategy

### Phased Approach
1. **Foundation:** Tailscale account setup, Vault integration, Kubernetes deployment
2. **Internal Networking:** NGINX deployment, service discovery, MagicDNS configuration
3. **Private Services:** Media, home automation, productivity apps migration
4. **Public Services:** Kibana and CCHS Makerspace Funnel configuration
5. **Monitoring:** Metrics integration, alerting, dashboard creation
6. **Validation:** End-to-end testing, performance validation, security review
7. **Cleanup:** NGINX Proxy Manager decommission, port forwarding removal, Cloudflare updates
8. **Documentation:** User guides, runbooks, service catalog, rollback procedures

### Rollback Capability
- **Duration:** Maintained for 90 days post-migration
- **Procedure:** Documented step-by-step in TAILSCALE-MIGRATION.md
- **Backups:** NGINX Proxy Manager config, Cloudflare DNS records, port forwarding rules
- **Trigger Criteria:** Service unavailability, performance degradation, security concerns

## Future Technology Additions

Based on roadmap priorities:
- **Service Mesh:** Istio or Linkerd for advanced traffic management
- **Backup Operator:** Velero for Kubernetes application backups
- **External Secrets:** external-secrets operator for Vault integration
- **Dependency Automation:** Renovate for automated dependency updates
- **Infrastructure Testing:** Terratest, Molecule, compliance scanning
- **Multi-Cluster:** Federation, centralized management plane
- **Auto-Scaling:** Horizontal Pod Autoscaler, cluster autoscaler
- **Tailscale SSH:** Replace traditional SSH with Tailscale SSH for enhanced security
- **Tailscale Serve:** Alternative to Funnel for internal-only HTTPS services
- **Exit Nodes:** Tailscale exit node for routing internet traffic through homelab
