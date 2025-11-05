# Homelab Infrastructure Platform

A production-grade, automated homelab infrastructure platform leveraging Infrastructure-as-Code principles for deploying and managing Kubernetes clusters, Elasticsearch, media services, and home automation on Proxmox.

## Overview

This repository provides a complete, reproducible infrastructure stack using:
- **Terraform** for infrastructure provisioning
- **Ansible** for configuration management
- **Kubernetes** for container orchestration (K3s and Kubespray options)
- **ArgoCD** for GitOps application deployment
- **HashiCorp Vault** for secrets management

The platform is designed to be secure, scalable, and maintainable with comprehensive automation and documentation for external adoption.

## Key Features

- **Infrastructure Automation**: Terraform modules for Proxmox VM provisioning with cloud-init
- **Kubernetes Options**:
  - **K3s**: Lightweight Kubernetes for rapid deployment
  - **Kubespray**: Production-grade Kubernetes with full control and customization
- **Elasticsearch Stack**: Dedicated cluster for logging, monitoring, and search capabilities
- **Media Management**: Automated media stack (Plex, Radarr, Sonarr, qBittorrent, Jackett)
- **Home Automation**: Home Assistant and Pi-hole for smart home and network management
- **Storage Integration**: Democratic CSI with TrueNAS/FreeNAS iSCSI and NFS backends
- **GitOps Deployment**: ArgoCD for declarative application management
- **Secret Management**: HashiCorp Vault integration for secure credential storage
- **Monitoring**: Prometheus, Grafana, and Elasticsearch/Kibana observability stack

## Kubernetes Deployment Options

### Kubespray (Recommended for Production)

Production-grade Kubernetes deployment with full control over cluster components.

**Features:**
- Full control over CNI, storage, ingress, and all components
- Better support for cluster upgrades and maintenance
- Distributed etcd for high availability
- Enterprise-grade reliability

**Quick Start:**
```bash
# See detailed guide: docs/KUBESPRAY-QUICKSTART.md

# 1. Provision VMs with Terraform
cd tf/kubespray
terraform apply -var-file=terraform.tfvars

# 2. Deploy cluster with Kubespray
cd ../../ansible
ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini \
  playbooks/deploy_kubespray_cluster.yml
```

**Documentation:**
- **Quick Start**: [docs/KUBESPRAY-QUICKSTART.md](docs/KUBESPRAY-QUICKSTART.md) - Fast deployment reference
- **Full Deployment**: [docs/KUBESPRAY-DEPLOYMENT.md](docs/KUBESPRAY-DEPLOYMENT.md) - Complete deployment guide
- **Operations**: [docs/KUBESPRAY-OPERATIONS.md](docs/KUBESPRAY-OPERATIONS.md) - Add/remove nodes, upgrades
- **Backup/Restore**: [docs/KUBESPRAY-BACKUP-RESTORE.md](docs/KUBESPRAY-BACKUP-RESTORE.md) - Disaster recovery
- **Troubleshooting**: [docs/KUBESPRAY-TROUBLESHOOTING.md](docs/KUBESPRAY-TROUBLESHOOTING.md) - Issue resolution
- **Architecture**: [docs/KUBESPRAY-ARCHITECTURE.md](docs/KUBESPRAY-ARCHITECTURE.md) - Design and components
- **Configuration**: [docs/KUBESPRAY-CONFIG-REFERENCE.md](docs/KUBESPRAY-CONFIG-REFERENCE.md) - Config reference

### K3s (Lightweight Alternative)

Lightweight Kubernetes distribution for rapid deployment and simplified management.

**Features:**
- Minimal resource requirements
- Single binary installation
- Built-in load balancer (Klipper)
- Quick setup and deployment

**Quick Start:**
```bash
# Deploy K3s VMs
cd tf/kubernetes
terraform apply

# Configure and deploy K3s
cd ../../ansible
ansible-playbook -i inventory 00_setup_host.yml
ansible-playbook -i inventory 01_setup_k8s.yml
ansible-playbook -i inventory 02_setup_first_cp_node.yml
ansible-playbook -i inventory 02_setup_other_cp_nodes.yml
ansible-playbook -i inventory 02_setup_worker.yml
```

**Documentation:**
- [docs/DEPLOYMENT-GUIDE.md](docs/DEPLOYMENT-GUIDE.md) - End-to-end K3s deployment

## Architecture

The platform follows a three-layer approach:

### 1. Infrastructure Layer (`tf/`)
Terraform configurations provision virtual machines on Proxmox:
- **Kubespray Cluster**: 6 nodes (3 control plane + 3 workers) with distributed etcd
- **K3s Cluster**: 6 VMs (3 control plane + 3 workers)
- **Elasticsearch Cluster**: 9 VMs (6 data nodes + 3 master nodes)
- **Application Servers**: Media, monitoring, and utility services
- **Network Configuration**: VLAN isolation, static IP assignment, DNS integration

### 2. Configuration Layer (`ansible/`)
Ansible playbooks configure hosts and deploy Kubernetes:
- Base host setup and hardening
- Kubespray cluster deployment and management
- K3s cluster initialization and node joining
- Storage driver configuration
- System package management

### 3. Application Layer (`k8s/`)
Kubernetes manifests and ArgoCD applications:
- Helm chart deployments via ArgoCD
- Application-specific configurations
- Storage class definitions
- Ingress and service mesh setup

## Quick Start

### Prerequisites

Before deploying this infrastructure, ensure you have:

1. **Hardware/Infrastructure**:
   - Proxmox VE cluster (tested on 7.x+)
   - TrueNAS/FreeNAS storage system
   - Domain name and DNS management capability
   - HashiCorp Vault instance (see [Vault Setup Guide](docs/VAULT-SETUP.md))

2. **Local Tools**:
   - Terraform >= 1.5.0
   - Ansible >= 2.15.0
   - kubectl >= 1.28.0
   - vault CLI >= 1.15.0
   - git-filter-repo (for repository sanitization)

3. **Credentials and Access**:
   - Proxmox API credentials
   - TrueNAS/FreeNAS API key
   - SSH access to target hosts
   - Vault access token

### Setup Steps

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/homelab.git
   cd homelab
   ```

2. **Set up Vault** (see [detailed guide](docs/VAULT-SETUP.md)):
   ```bash
   cd vault/scripts
   ./01-initialize-vault.sh
   ./02-unseal-vault.sh
   ./03-configure-vault.sh
   ```

3. **Configure secrets in Vault**:
   ```bash
   export VAULT_ADDR="https://192.168.10.101:8200"
   vault login

   # Store Proxmox credentials
   vault kv put secret/homelab/proxmox/terraform \
     username="terraform@pve" \
     password="your-password"

   # Store TrueNAS credentials
   vault kv put secret/homelab/freenas/credentials \
     api_key="your-api-key"
   ```

4. **Choose deployment method**:
   - **Kubespray**: See [docs/KUBESPRAY-QUICKSTART.md](docs/KUBESPRAY-QUICKSTART.md)
   - **K3s**: See [docs/DEPLOYMENT-GUIDE.md](docs/DEPLOYMENT-GUIDE.md)

5. **Deploy applications**:
   ```bash
   # Deploy storage drivers
   kubectl apply -f k8s/democratic-csi/

   # Deploy monitoring stack
   kubectl apply -f k8s/prometheus-stack-app.yaml

   # Deploy applications via ArgoCD
   kubectl apply -f k8s/argocd/platform-apps.yaml
   ```

## Security and Secret Management

This repository follows security best practices with **zero secrets in code**:

- **Vault Integration**: All credentials stored in HashiCorp Vault
- **Example Files**: All sensitive configs have `.example` versions with placeholders
- **Git History**: Sanitization scripts remove secrets from entire repository history
- **Secret Scanning**: Automated GitHub Actions workflows prevent credential commits
- **Access Control**: Vault policies enforce least-privilege access

For complete documentation on secret management, see [docs/SECRET-MANAGEMENT.md](docs/SECRET-MANAGEMENT.md).

## Documentation

### Core Infrastructure
- **[Vault Setup Guide](docs/VAULT-SETUP.md)**: Complete Vault installation, initialization, and secret organization
- **[Secret Management](docs/SECRET-MANAGEMENT.md)**: Vault usage patterns, Terraform/Ansible integration
- **[Git History Sanitization](docs/SANITIZING-GIT-HISTORY.md)**: Remove secrets from repository history
- **[Security Best Practices](docs/SECURITY.md)**: Network isolation, credential rotation, scanning

### Kubespray Kubernetes (Production)
- **[Quick Start](docs/KUBESPRAY-QUICKSTART.md)**: Fast deployment reference
- **[Deployment Guide](docs/KUBESPRAY-DEPLOYMENT.md)**: Complete deployment procedures
- **[Operations](docs/KUBESPRAY-OPERATIONS.md)**: Node management, upgrades, maintenance
- **[Backup/Restore](docs/KUBESPRAY-BACKUP-RESTORE.md)**: Disaster recovery and backup procedures
- **[Troubleshooting](docs/KUBESPRAY-TROUBLESHOOTING.md)**: Common issues and resolution
- **[Architecture](docs/KUBESPRAY-ARCHITECTURE.md)**: Cluster design and components
- **[Config Reference](docs/KUBESPRAY-CONFIG-REFERENCE.md)**: Configuration file reference

### K3s Kubernetes (Lightweight)
- **[Deployment Guide](docs/DEPLOYMENT-GUIDE.md)**: End-to-end K3s deployment workflow

## Network Architecture

The infrastructure uses VLAN isolation and static IP addressing:

- **Management VLAN**: 192.168.10.0/24 - Infrastructure services
  - Kubespray Cluster: 192.168.10.234-239 (km01-km03, kube01-kube03)
  - K3s Cluster: 192.168.10.11-16
  - Elasticsearch: 192.168.10.31-39
  - Vault: 192.168.10.101
- **Service Network** (Kubespray): 10.233.0.0/18
- **Pod Network** (Kubespray): 10.233.64.0/18
- **MetalLB Pool**: 192.168.100.0/24
- **Gateway**: 192.168.10.1
- **DNS**: Internal DNS server with lab.thewortmans.org domain

## Storage

Storage is provided by TrueNAS/FreeNAS via Democratic CSI:

- **iSCSI Storage Class**: `freenas-iscsi-csi` for block storage (databases, stateful apps)
- **NFS Storage Class**: `freenas-nfs-csi` for shared storage (media, logs)
- **Dynamic Provisioning**: Automatic PV creation and management
- **Snapshots**: CSI snapshot support for backup and recovery

## Troubleshooting

### Vault Connection Issues
```bash
# Check Vault status
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY=true
vault status

# Unseal if needed
vault operator unseal
```

### Terraform Provider Issues
```bash
# Re-initialize providers
cd tf/kubespray  # or tf/kubernetes for K3s
rm -rf .terraform
terraform init
```

### Kubernetes Cluster Issues
```bash
# Check cluster status
kubectl get nodes
kubectl get pods -A

# View logs (Kubespray)
ssh bret@km01
sudo journalctl -u kubelet -f

# View logs (K3s)
ssh bret@kube01
sudo journalctl -u k3s -f
```

### Storage Issues
```bash
# Check CSI driver status
kubectl get pods -n democratic-csi
kubectl logs -n democratic-csi <pod-name>

# Verify TrueNAS connectivity
ping <truenas-ip>
```

### Getting Help

1. Check component-specific documentation in `docs/`
2. Review application logs via `kubectl logs`
3. Check ArgoCD dashboard for application status
4. Review Grafana dashboards for infrastructure metrics

## Project Structure

```
homelab/
├── tf/                      # Terraform infrastructure
│   ├── kubespray/           # Kubespray cluster VMs
│   ├── kubernetes/          # K3s cluster VMs
│   ├── lab/                 # Elasticsearch cluster VMs
│   ├── home-apps/           # Application server VMs
│   └── modules/             # Reusable Terraform modules
├── ansible/                 # Configuration management
│   ├── inventory/           # Host definitions
│   └── playbooks/           # Ansible playbooks
├── kubespray/               # Kubespray configuration
│   └── inventory/homelab/   # Kubespray inventory and group_vars
├── k8s/                     # Kubernetes applications
│   ├── democratic-csi/      # Storage drivers
│   ├── metallb/             # LoadBalancer
│   ├── traefik/             # Ingress controller
│   ├── cert-manager/        # Certificate management
│   ├── argocd/              # GitOps automation
│   └── *-app.yaml           # ArgoCD applications
├── vault/                   # Vault setup
│   └── scripts/             # Initialization scripts
├── docs/                    # Documentation
└── scripts/                 # Utility scripts
```

## Contributing

This is a personal homelab project, but suggestions and improvements are welcome. Please open an issue to discuss proposed changes.

## License

This project is open source. License details to be determined.

## Acknowledgments

Built with open source tools:
- [Terraform](https://www.terraform.io/)
- [Ansible](https://www.ansible.com/)
- [Kubespray](https://kubespray.io/)
- [K3s](https://k3s.io/)
- [ArgoCD](https://argoproj.github.io/cd/)
- [HashiCorp Vault](https://www.vaultproject.io/)
- [Democratic CSI](https://github.com/democratic-csi/democratic-csi)
- [Proxmox VE](https://www.proxmox.com/en/proxmox-ve)
