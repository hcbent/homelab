# Product Mission

## Pitch
Homelab Infrastructure Platform is a production-grade, self-hosted infrastructure management system that helps homelab enthusiasts, infrastructure engineers, and self-hosting advocates build and operate enterprise-class infrastructure at home by providing complete automation, security hardening, and GitOps-based infrastructure-as-code workflows.

## Users

### Primary Customers
- **Homelab Enthusiasts**: Individuals building sophisticated home infrastructure for learning, experimentation, and personal projects
- **Self-Hosting Advocates**: People who prefer to maintain control over their data and services by running infrastructure at home
- **Infrastructure Engineers**: Professionals learning or testing enterprise technologies in a home environment
- **Small Tech Teams**: Small businesses or startups using homelab infrastructure for development, testing, or production workloads

### User Personas

**Infrastructure Builder** (25-45 years old)
- **Role:** DevOps Engineer, SRE, System Administrator, or Technical Hobbyist
- **Context:** Maintains home infrastructure for learning cloud-native technologies, testing production scenarios, or hosting personal/family services
- **Pain Points:**
  - Manual VM provisioning is time-consuming and error-prone
  - Secrets scattered across files and git history create security risks
  - Lack of standardization makes infrastructure fragile and hard to rebuild
  - Complex multi-node deployments require extensive manual coordination
  - No clear disaster recovery or rebuild strategy
- **Goals:**
  - Automate infrastructure provisioning and configuration
  - Implement security best practices with proper secret management
  - Build reproducible, documented infrastructure that can be rebuilt from code
  - Run production-grade applications (Kubernetes, Elasticsearch, monitoring) at home
  - Learn enterprise technologies in a safe, cost-effective environment

**Self-Hosting Administrator** (30-50 years old)
- **Role:** Privacy-conscious individual or small business owner
- **Context:** Runs personal or business services (media servers, file storage, home automation, communication tools) on self-hosted infrastructure
- **Pain Points:**
  - Commercial cloud services are expensive and compromise data privacy
  - Managing multiple services manually is overwhelming
  - Concerned about data breaches from storing secrets in configuration files
  - Infrastructure downtime affects family or business operations
  - Limited technical expertise makes complex setups intimidating
- **Goals:**
  - Host personal services (Plex, Home Assistant, file storage) reliably
  - Maintain data privacy and control
  - Implement proper backups and security without deep expertise
  - Minimize maintenance overhead through automation
  - Have confidence in disaster recovery capabilities

## The Problem

### Secret Management Crisis
Traditional homelab setups store credentials, API keys, and passwords directly in configuration files or worse, commit them to git repositories. This creates serious security vulnerabilities where:
- Secrets are exposed in version control history, even after deletion
- Anyone with repository access can view production credentials
- Credential rotation requires manual file updates across multiple systems
- No audit trail exists for secret access or modifications

**Our Solution:** Centralized HashiCorp Vault deployment with automated secret provisioning, policy-based access control, comprehensive audit logging, and integration with all infrastructure tools (Terraform, Ansible, Kubernetes).

### Infrastructure Fragility
Many homelabs are built through manual configuration, creating "snowflake" systems that cannot be reliably rebuilt after failures. Documentation becomes outdated, configuration drift accumulates, and disaster recovery is uncertain or impossible.

**Our Solution:** Complete infrastructure-as-code approach using Terraform for VM provisioning, Ansible for configuration management, and GitOps for Kubernetes applications. Every component is defined in version-controlled code that serves as living documentation and enables one-command rebuilds.

### Manual Provisioning Overhead
Creating and managing virtual machines, configuring clusters, and deploying applications manually is time-consuming and error-prone. Multi-node deployments (Kubernetes clusters, Elasticsearch clusters) require extensive coordination and are particularly challenging.

**Our Solution:** Automated provisioning pipelines with modular Terraform configurations, reusable Ansible playbooks, and ArgoCD-based GitOps for continuous deployment. Infrastructure changes are version-controlled, reviewed, and applied consistently.

### Lack of Production Best Practices
Homelab infrastructure often lacks enterprise-grade features like monitoring, logging, high availability, proper networking, and storage management. This results in unreliable services and limited learning opportunities for production technologies.

**Our Solution:** Production-ready stack including Prometheus/Grafana monitoring, Elasticsearch/Kibana logging, Democratic CSI storage orchestration, MetalLB load balancing, and multi-node Kubernetes with separate control plane and worker nodes.

## Differentiators

### Enterprise-Grade Secret Management for Homelabs
Unlike typical homelab setups that scatter secrets across configuration files, we provide standalone HashiCorp Vault integration as a first-class feature. This results in production-level security, automated credential rotation, comprehensive audit trails, and safe public repository sharing.

### Complete Multi-Layer Automation Stack
While most homelab projects focus on a single layer (either VMs, configuration, or applications), we provide end-to-end automation from bare metal to running applications. This results in reproducible infrastructure that can be rebuilt in hours instead of days or weeks.

### GitOps-First Architecture
Unlike manual configuration approaches, every infrastructure component is defined in version-controlled code with clear separation of concerns (Terraform for infrastructure, Ansible for configuration, ArgoCD for applications). This results in auditable changes, easy rollbacks, and infrastructure that serves as its own documentation.

### Production Patterns at Home Scale
Unlike enterprise solutions that are too complex/expensive or simple tutorials that skip critical features, we implement production best practices (multi-node clusters, monitoring, logging, storage orchestration) at homelab scale. This results in valuable learning opportunities while maintaining manageable complexity and cost.

## Key Features

### Infrastructure Provisioning
- **Terraform VM Management:** Modular, reusable Terraform configurations for Proxmox VM provisioning with separate state management for different environments (Kubernetes, Elasticsearch, applications)
- **Multi-Environment Support:** Independent infrastructure stacks for Kubernetes clusters, Elasticsearch clusters, and home applications with isolated state files preventing cross-environment interference
- **Cloud-Init Automation:** Standardized Ubuntu VM templates with automated SSH key deployment, network configuration, and initial user setup

### Secret Management & Security
- **HashiCorp Vault Integration:** Standalone Vault server with complete secret lifecycle management, automated unsealing scripts, and credential rotation workflows
- **Terraform Vault Provider:** Native integration allowing Terraform to read Proxmox, FreeNAS, and application credentials directly from Vault without storing secrets in code
- **Ansible Vault Integration:** Ansible playbooks retrieve secrets dynamically from Vault using hashi_vault lookup plugin with policy-based access control
- **Git History Sanitization:** Tools and documentation for removing exposed secrets from git history and preventing future commits

### Configuration Management
- **Ansible Automation:** Comprehensive playbooks for host configuration, Kubernetes cluster setup (control plane and workers), Elasticsearch deployment, and service management
- **Sequential Cluster Deployment:** Orchestrated playbooks for building multi-node Kubernetes clusters with proper control plane initialization and worker node joining
- **Rolling Updates:** Safe upgrade procedures for Elasticsearch clusters with health checks and gradual node updates

### Kubernetes Platform
- **Multi-Node K3s Cluster:** Production-grade Kubernetes with separate control plane (kube01-03) and worker nodes (kube04-06) for high availability and workload separation
- **ArgoCD GitOps:** Declarative application deployment with automated syncing from git repositories, multi-source Helm deployments, and namespace management
- **Storage Orchestration:** Democratic CSI with FreeNAS iSCSI and NFS backends providing persistent volume provisioning for stateful applications

### Observability & Monitoring
- **Prometheus Stack:** Complete monitoring solution with Prometheus metrics collection, Grafana visualization, and AlertManager notifications
- **Elasticsearch Logging:** Dedicated 9-node Elasticsearch cluster with separate master and data nodes, Kibana dashboards, and Fleet for log aggregation
- **Application Monitoring:** Integrated monitoring for all deployed applications with custom dashboards and alerting rules

### Application Hosting
- **Media Management Stack:** Plex media server, Radarr/Sonarr/Lidarr for media automation, qBittorrent for downloads, and Jackett for indexer management
- **Home Automation:** Home Assistant for smart home control, Pi-hole for network-wide ad blocking and DNS management
- **LLM Services:** Ollama for API-based LLM inference and Text Generation WebUI for interactive LLM access with GPU acceleration support
- **Productivity Tools:** Mealie for recipe management, Paperless-ngx for document management, Actual Budget for financial tracking

### Infrastructure Services
- **Load Balancing:** MetalLB providing LoadBalancer services on bare metal Kubernetes with IP address pool management
- **Ingress & TLS:** Traefik ingress controller with automatic TLS certificate management via step-certificates internal CA
- **Network Management:** VLAN support, DNS resolution via internal DNS server, and proper gateway configuration for all VMs
- **Storage Backend:** TrueNAS/FreeNAS integration with iSCSI for block storage and NFS for shared filesystems

### Developer Experience
- **Helper Scripts:** Automated tools for adding VMs, generating configurations, extracting Kubernetes tokens, and managing clusters
- **Comprehensive Documentation:** Detailed deployment guides, security policies, Vault integration examples, and troubleshooting procedures
- **Modular Architecture:** Reusable Terraform modules, Ansible roles, and Helm values enabling easy customization and extension
