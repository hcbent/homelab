# Homelab Infrastructure Platform

A production-grade, automated homelab infrastructure platform leveraging Infrastructure-as-Code principles for deploying and managing Kubernetes clusters, Elasticsearch, media services, and home automation on Proxmox.

## Overview

This repository provides a complete, reproducible infrastructure stack using:
- **Terraform** for infrastructure provisioning
- **Ansible** for configuration management
- **K3s** for Kubernetes orchestration
- **ArgoCD** for GitOps application deployment
- **HashiCorp Vault** for secrets management

The platform is designed to be secure, scalable, and maintainable with comprehensive automation and documentation for external adoption.

## Key Features

- **Infrastructure Automation**: Terraform modules for Proxmox VM provisioning with cloud-init
- **Kubernetes Cluster**: High-availability K3s cluster with control plane and worker nodes
- **Elasticsearch Stack**: Dedicated cluster for logging, monitoring, and search capabilities
- **Media Management**: Automated media stack (Plex, Radarr, Sonarr, qBittorrent, Jackett)
- **Home Automation**: Home Assistant and Pi-hole for smart home and network management
- **Storage Integration**: Democratic CSI with TrueNAS/FreeNAS iSCSI and NFS backends
- **GitOps Deployment**: ArgoCD for declarative application management
- **Secret Management**: HashiCorp Vault integration for secure credential storage
- **Monitoring**: Prometheus, Grafana, and Elasticsearch/Kibana observability stack

## Architecture

The platform follows a three-layer approach:

### 1. Infrastructure Layer (`tf/`)
Terraform configurations provision virtual machines on Proxmox:
- **Kubernetes Cluster**: 6 VMs (3 control plane + 3 workers)
- **Elasticsearch Cluster**: 9 VMs (6 data nodes + 3 master nodes)
- **Application Servers**: Media, monitoring, and utility services
- **Network Configuration**: VLAN isolation, static IP assignment, DNS integration

### 2. Configuration Layer (`ansible/`)
Ansible playbooks configure hosts and deploy Kubernetes:
- Base host setup and hardening
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

4. **Create configuration files from examples**:
   ```bash
   # Terraform configurations
   cp tf/kubernetes/terraform.tfvars.example tf/kubernetes/terraform.tfvars
   cp tf/lab/terraform.tfvars.example tf/lab/terraform.tfvars

   # Kubernetes storage configurations
   cp k8s/helm/values/freenas-nfs.yaml.example k8s/helm/values/freenas-nfs.yaml
   cp k8s/helm/values/freenas-iscsi.yaml.example k8s/helm/values/freenas-iscsi.yaml

   # Ansible inventory files
   cp ansible/inventory/lab.example ansible/inventory/lab

   # Docker compose configurations
   cp docker/docker-compose.yml.example docker/docker-compose.yml

   # Edit files and replace VAULT_SECRET_REFERENCE placeholders
   # with actual values retrieved from Vault
   ```

5. **Deploy infrastructure** (see [detailed guide](docs/DEPLOYMENT-GUIDE.md)):
   ```bash
   # Deploy Kubernetes VMs
   cd tf/kubernetes
   terraform init
   terraform plan
   terraform apply

   # Configure hosts and deploy K3s
   cd ../../ansible
   ansible-playbook -i inventory 00_setup_host.yml
   ansible-playbook -i inventory 01_setup_k8s.yml
   ansible-playbook -i inventory 02_setup_first_cp_node.yml
   ansible-playbook -i inventory 02_setup_other_cp_nodes.yml
   ansible-playbook -i inventory 02_setup_worker.yml
   ```

6. **Deploy applications**:
   ```bash
   # Deploy storage drivers
   kubectl apply -f k8s/democratic-csi/

   # Deploy monitoring stack
   kubectl apply -f k8s/prometheus-stack-app.yaml

   # Deploy applications via ArgoCD
   kubectl apply -f k8s/llm-app.yaml
   ```

## Security and Secret Management

This repository follows security best practices with **zero secrets in code**:

- **Vault Integration**: All credentials stored in HashiCorp Vault
- **Example Files**: All sensitive configs have `.example` versions with placeholders
- **Git History**: Sanitization scripts remove secrets from entire repository history
- **Secret Scanning**: Automated GitHub Actions workflows prevent credential commits
- **Access Control**: Vault policies enforce least-privilege access

### Using Example Files

This repository uses the `.example` file pattern for all configuration files containing secrets. This ensures that sensitive credentials are never committed to version control while providing clear templates for external users.

#### Example File Pattern

All sensitive configuration files have corresponding `.example` versions that:
- Provide complete file structure with all required fields
- Use placeholder values for secrets: `VAULT_SECRET_REFERENCE`
- Include inline comments showing the Vault path to retrieve each secret
- Are tracked in git, while the real files (without `.example`) are gitignored

**Example: Terraform variables file**
```hcl
# tf/kubernetes/terraform.tfvars.example
# Proxmox API credentials are retrieved from Vault
# pm_user = ""       # Retrieved from: vault kv get -field=username secret/homelab/proxmox/terraform
# pm_password = ""   # Retrieved from: vault kv get -field=password secret/homelab/proxmox/terraform

vms = [
  {
    name = "kube01"
    # ... VM configuration
  }
]
```

**Example: Kubernetes secret manifest**
```yaml
# k8s/pihole/pihole.yaml.example
apiVersion: v1
kind: Secret
metadata:
  name: pihole-secret
data:
  # Retrieve from Vault: vault kv get -field=webpassword secret/homelab/pihole/lab/credentials
  # Then base64 encode: echo -n "password" | base64
  WEBPASSWORD: REPLACE_WITH_BASE64_ENCODED_PASSWORD
```

**Example: Docker Compose file**
```yaml
# docker/docker-compose.yml.example
services:
  app:
    environment:
      # Retrieve from Vault: vault kv get -field=api_key secret/homelab/apps/service
      - API_KEY=VAULT_SECRET_REFERENCE
```

**Example: Ansible inventory**
```ini
# ansible/inventory/lab.example
[elasticsearch_all:vars]
# Retrieve from Vault: vault kv get -field=username secret/homelab/elasticsearch/lab/credentials
elasticsearch_username=VAULT_SECRET_REFERENCE
# Retrieve from Vault: vault kv get -field=password secret/homelab/elasticsearch/lab/credentials
elasticsearch_password=VAULT_SECRET_REFERENCE
```

#### Using Example Files

To use an example file:

1. **Copy the `.example` file**:
   ```bash
   cp config.yaml.example config.yaml
   ```

2. **Retrieve secrets from Vault**:
   ```bash
   export VAULT_ADDR="https://192.168.10.101:8200"
   vault login
   vault kv get secret/homelab/service/credentials
   ```

3. **Replace placeholders**:
   - Replace `VAULT_SECRET_REFERENCE` with actual values from Vault
   - Follow inline comments for the correct Vault path for each secret
   - For base64-encoded secrets (Kubernetes), encode the value before inserting

4. **The real file is gitignored**:
   - Files without `.example` suffix are automatically gitignored
   - Your credentials will never be committed to version control

#### Available Example Files

The repository includes `.example` versions for:

**Terraform configurations**:
- `tf/kubernetes/terraform.tfvars.example` - Kubernetes cluster VMs
- `tf/lab/terraform.tfvars.example` - Elasticsearch cluster VMs
- `tf/elasticsearch.tfvars.example` - Elasticsearch-specific configuration
- `tf/homelab.tfvars.example` - General homelab VMs
- `tf/vault/terraform.tfvars.example` - Vault server VM

**Kubernetes manifests**:
- `k8s/helm/values/freenas-nfs.yaml.example` - NFS storage driver
- `k8s/helm/values/freenas-iscsi.yaml.example` - iSCSI storage driver
- `k8s/pihole/pihole.yaml.example` - Pi-hole deployment
- `k8s/lab-cluster/aws_secret.yaml.example` - AWS S3 credentials
- `k8s/basement/eck-license-secret.yaml.example` - Elastic Cloud license

**Ansible inventories**:
- `ansible/inventory/lab.example` - Lab Elasticsearch cluster
- `ansible/inventory/cchs.example` - CCHS Elasticsearch cluster
- `ansible/inventory/monitoring.example` - Monitoring cluster
- `ansible/playbooks/add_agent.yml.example` - Elastic Agent deployment
- `ansible/playbooks/deploy_pihole.yml.example` - Pi-hole deployment

**Docker Compose**:
- `docker/docker-compose.yml.example` - Media stack services
- `docker/home-apps/docker-compose.yml.example` - Home application services

For complete documentation on secret management, see [docs/SECRET-MANAGEMENT.md](docs/SECRET-MANAGEMENT.md).

## Documentation

Detailed guides are available in the `docs/` directory:

- **[Vault Setup Guide](docs/VAULT-SETUP.md)**: Complete Vault installation, initialization, and secret organization
- **[Deployment Guide](docs/DEPLOYMENT-GUIDE.md)**: End-to-end infrastructure deployment workflow
- **[Secret Management](docs/SECRET-MANAGEMENT.md)**: Vault usage patterns, Terraform/Ansible integration
- **[Git History Sanitization](docs/SANITIZING-GIT-HISTORY.md)**: Remove secrets from repository history
- **[Security Best Practices](docs/SECURITY.md)**: Network isolation, credential rotation, scanning
- **[Pre-Public Checklist](docs/PRE-PUBLIC-CHECKLIST.md)**: Verification steps before making repository public

## Network Architecture

The infrastructure uses VLAN isolation and static IP addressing:

- **Management VLAN**: 192.168.10.0/24 - Infrastructure services
  - Kubernetes: 192.168.10.11-16
  - Elasticsearch: 192.168.10.31-39
  - Vault: 192.168.10.101
- **Application VLAN**: Separate network for media and home services
- **Gateway**: 192.168.10.1
- **DNS**: Internal DNS server with lab.thewortmans.org domain

## Storage

Storage is provided by TrueNAS/FreeNAS via Democratic CSI:

- **iSCSI Storage Class**: `freenas-iscsi-csi` for block storage (databases, stateful apps)
- **NFS Storage Class**: `freenas-nfs-csi` for shared storage (media, logs)
- **Dynamic Provisioning**: Automatic PV creation and management
- **Snapshots**: CSI snapshot support for backup and recovery

## Troubleshooting

### Common Issues

**Vault Connection Issues**:
```bash
# Check Vault status
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY=true
vault status

# Unseal if needed
vault operator unseal
```

**Terraform Provider Issues**:
```bash
# Re-initialize providers
cd tf/kubernetes
rm -rf .terraform
terraform init
```

**K3s Cluster Issues**:
```bash
# Check cluster status
kubectl get nodes
kubectl get pods -A

# View logs on control plane
ssh bret@kube01
sudo journalctl -u k3s -f
```

**Storage Issues**:
```bash
# Check CSI driver status
kubectl get pods -n democratic-csi
kubectl logs -n democratic-csi <pod-name>

# Verify TrueNAS connectivity
ping 192.168.2.24
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
│   ├── kubernetes/          # K8s cluster VMs
│   ├── lab/                 # Elasticsearch cluster VMs
│   ├── home-apps/           # Application server VMs
│   └── modules/             # Reusable Terraform modules
├── ansible/                 # Configuration management
│   ├── inventory/           # Host definitions
│   └── playbooks/           # Ansible playbooks
├── k8s/                     # Kubernetes applications
│   ├── democratic-csi/      # Storage drivers
│   ├── helm/                # Helm configurations
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
- [K3s](https://k3s.io/)
- [ArgoCD](https://argoproj.github.io/cd/)
- [HashiCorp Vault](https://www.vaultproject.io/)
- [Democratic CSI](https://github.com/democratic-csi/democratic-csi)
- [Proxmox VE](https://www.proxmox.com/en/proxmox-ve)
