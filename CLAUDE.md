# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Architecture

This is a homelab infrastructure repository with three main deployment layers:

1. **Infrastructure Layer** (`../tf/`): Terraform configurations for provisioning Proxmox VMs
2. **Host Configuration** (`../ansible/`): Ansible playbooks for configuring hosts and Kubernetes clusters  
3. **Application Layer** (`k8s/`): Kubernetes manifests and Helm configurations for applications

### Key Components

- **VM Infrastructure**: Terraform modules create VMs on Proxmox with configurable specs (cores, memory, storage)
- **Kubernetes Cluster**: Multi-node cluster with control plane (kube01-03) and worker nodes (kube04-06)
- **Elasticsearch Cluster**: Dedicated nodes (es01-09) with separate masters, data nodes, Kibana, and Fleet
- **Monitoring Stack**: Prometheus, Grafana, and Elasticsearch/Kibana for observability
- **Media Stack**: Plex, Radarr, Sonarr, qBittorrent, Jackett for media management
- **Home Automation**: Home Assistant, Pi-hole for DNS filtering
- **Storage**: Democratic CSI with FreeNAS iSCSI/NFS backends
- **LLM Services**: Ollama and Text Generation WebUI for AI/ML workloads

## Common Commands

### Terraform Operations (from ../tf directory)
```bash
# Initialize and apply infrastructure
terraform init
terraform plan -var-file homelab.tfvars
terraform apply -var-file homelab.tfvars
```

### Ansible Operations (from ../ansible directory)
```bash
# Sequential cluster setup playbooks
ansible-playbook -i inventory 00_setup_host.yml         # Base host configuration
ansible-playbook -i inventory 01_setup_k8s.yml          # Kubernetes prerequisites  
ansible-playbook -i inventory 02_setup_first_cp_node.yml # First control plane node
ansible-playbook -i inventory 02_setup_other_cp_nodes.yml # Additional control plane nodes
ansible-playbook -i inventory 02_setup_worker.yml       # Worker nodes

# Utility playbooks
ansible-playbook -i inventory 01_setup_proxy.yml        # Proxy server setup
ansible-playbook -i inventory upgrade_all_pkgs.yml      # Package updates
```

### Kubernetes Operations
```bash
# Deploy applications via ArgoCD apps
kubectl apply -f llm-app.yaml                    # Ollama LLM server
kubectl apply -f prometheus-stack-app.yaml       # Monitoring stack
kubectl apply -f elasticsearch-app.yaml          # Elasticsearch cluster

# Utility scripts
./get-skooner-token.sh                           # Get Kubernetes dashboard token
./setup_initial_cluster.sh                      # K3s cluster bootstrap
./add_node_to_cluster.sh                        # Add nodes to existing cluster

# Check cluster status
kubectl get nodes
kubectl get pods -A
kubectl get applications -n argocd               # ArgoCD applications status
```

## ArgoCD Application Pattern

Applications follow the ArgoCD Application pattern in `*-app.yaml` files:
- **Source**: Helm charts from public repositories (e.g., prometheus-community, elastic.co)
- **Destination**: Specific namespaces on local cluster (`https://kubernetes.default.svc`)
- **Sync policies**: Automated deployment with `CreateNamespace` support
- **Values files**: Referenced from dedicated directories using `$values/path/file.yaml` syntax
- **Multi-source**: Combines remote Helm chart with local values repository

### ArgoCD Application Examples
- `llm-app.yaml`: Ollama LLM server (otwld/ollama-helm → llm namespace)
- `prometheus-stack-app.yaml`: Monitoring (prometheus-community → prometheus namespace)
- `elasticsearch-app.yaml`: ELK stack (elastic.co → elastic-stack namespace)

## File Organization

- `k8s/basement/`: Experimental/deprecated configurations
- `k8s/helm/values/`: Legacy Helm values files (being migrated)
- `k8s/home-apps/`: Legacy Kubernetes YAML deployments
- `k8s/[app-name]/`: Application-specific configurations and values
- `k8s/llm/`: LLM-specific Helm values (Ollama, Text Generation WebUI)
- `../ansible/inventory`: Host groupings for playbook execution
- `k8s/helm/values/vault.yaml`: HashiCorp Vault configuration

## Infrastructure Components

### Storage Classes
- **`freenas-iscsi-csi`**: Primary iSCSI storage class for persistent volumes
- **`freenas-nfs-csi`**: NFS storage class for shared storage needs
- **Democratic CSI**: Storage orchestration with FreeNAS integration

### Networking and Ingress
- **Load Balancing**: MetalLB for bare metal LoadBalancer services
- **Ingress Controller**: Traefik for HTTP(S) routing and TLS termination
- **DNS**: Pi-hole for network-wide ad blocking and local resolution
- **Certificate Management**: step-certificates for internal CA and TLS

### Host Inventory Groups (from ../ansible/inventory)
- **k8s_cp**: Control plane nodes (kube01-03)
- **k8s_worker**: Worker nodes (kube04-06) 
- **elasticsearch_nodes**: Data nodes (es01-06)
- **elasticsearch_masters**: Master nodes (es07-09)
- **infrastructure**: Support services (infra, proxy, plex, torrent, pihole)

## GPU and Specialized Workloads

### Node Selection and Resource Allocation
- **GPU Workloads**: Use `nodeSelector: {accelerator: nvidia-tesla-gpu}` 
- **GPU Resources**: `nvidia.com/gpu: 1` for LLM and AI/ML workloads
- **Tolerations**: Required for GPU nodes with `nvidia.com/gpu` taint

### LLM and AI Services
- **Ollama**: API-focused LLM server with model pre-loading
- **Text Generation WebUI**: Full-featured web interface for LLM interaction
- **Resource Requirements**: 8-16Gi memory, GPU allocation, persistent model storage

## Security and Operational Practices

- **Vault Integration**: HashiCorp Vault for secret management (`k8s/helm/values/vault.yaml`)
- **Network Policies**: Ingress controls and namespace isolation
- **RBAC**: Service accounts with appropriate cluster roles (e.g., `skooner-auth.yaml`)
- **Certificate Management**: Automated TLS with step-certificates and cert-manager
- **Storage Security**: CSI with secure iSCSI/NFS backends
- Put all docker compose files under the docker/ directory.