# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Architecture

This is a homelab infrastructure repository with three main deployment layers:

1. **Infrastructure Layer** (`tf/`): Terraform configurations for provisioning Proxmox VMs
2. **Host Configuration** (`ansible/`): Ansible playbooks for configuring hosts and Kubernetes clusters
3. **Application Layer** (`k8s/`): Kubernetes manifests and Helm configurations for applications

### Key Components

- **VM Infrastructure**: Terraform modules create VMs on Proxmox with configurable specs (cores, memory, storage)
- **Kubernetes Cluster**: Multi-node cluster with control plane (kube01-03) and worker nodes (kube04-06)
- **Monitoring Stack**: Prometheus, Grafana, and Elasticsearch/Kibana for observability
- **Media Stack**: Plex, Radarr, Sonarr, qBittorrent, Jackett for media management
- **Home Automation**: Home Assistant, Pi-hole for DNS filtering
- **Storage**: Mixed NFS/iSCSI storage with FreeNAS integration

## Common Commands

### Terraform Operations
```bash
# Initialize and apply infrastructure
terraform init
terraform plan -var-file homelab.tfvars
terraform apply -var-file homelab.tfvars
```

### Ansible Operations
```bash
# Run playbooks against inventory groups
ansible-playbook -i inventory 00_setup_host.yml
ansible-playbook -i inventory 01_setup_k8s.yml
ansible-playbook -i inventory 02_setup_first_cp_node.yml
```

### Kubernetes Operations
```bash
# Deploy applications via ArgoCD apps
kubectl apply -f k8s/prometheus-stack-app.yaml
kubectl apply -f k8s/elasticsearch-app.yaml

# Check cluster status
kubectl get nodes
kubectl get pods -A
```

## ArgoCD Application Pattern

Applications follow the ArgoCD Application pattern in `*-app.yaml` files:
- Source: Helm charts from public repositories
- Destination: Specific namespaces on local cluster
- Sync policies with automated deployment
- Values files referenced from `k8s/helm/values/`

## File Organization

- `k8s/basement/`: Experimental/deprecated configurations
- `k8s/helm/values/`: Helm values files for applications
- `k8s/home-apps/`: Legacy Kubernetes YAML deployments
- `k8s/[app-name]/`: Application-specific configurations
- `ansible/inventory`: Host groupings for playbook execution
- `vault/`: HashiCorp Vault configuration and secrets

## Storage Classes and Networking

The cluster uses:
- **Storage**: Democratic CSI with FreeNAS iSCSI/NFS backends
- **Load Balancing**: MetalLB for bare metal LoadBalancer services
- **Ingress**: Traefik for HTTP(S) routing
- **DNS**: Pi-hole for network-wide ad blocking

## Security Considerations

- Vault integration for secret management
- Network policies and ingress controls
- SSH key management via Ansible
- Certificate management with step-certificates