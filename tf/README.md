# Terraform VM Management

This directory contains Terraform configurations for managing VMs in your Proxmox homelab.

## Directory Structure

- `tf/elasticsearch/` - Elasticsearch cluster configuration (separate state)
- `tf/kubernetes/` - Kubernetes cluster configuration (separate state)
- `tf/modules/` - Shared Terraform modules
- `tf/homelab.tfvars` - Legacy combined configuration

## Usage

### Deploy Elasticsearch Cluster
```bash
cd tf/elasticsearch/
terraform init
terraform plan
terraform apply
```

### Deploy Kubernetes Cluster
```bash
cd tf/kubernetes/
terraform init
terraform plan
terraform apply
```

### Deploy Both Independently
Each cluster has its own state file and can be managed completely separately:
```bash
# Terminal 1 - Elasticsearch
cd tf/elasticsearch/
terraform apply

# Terminal 2 - Kubernetes (won't affect Elasticsearch)
cd tf/kubernetes/
terraform apply
```

## Why Separate Directories?

**Problem with shared state:** Using different tfvars files with the same Terraform configuration replaces the entire VM list, causing one cluster to destroy the other.

**Solution:** Separate directories with their own state files ensure:
- **Independent state management**: Each cluster tracked separately
- **No interference**: Changes to one cluster don't affect the other
- **Safer operations**: Destroy one cluster without touching the other

## Configuration

Each directory contains:
- `main.tf` - VM module instantiation
- `variables.tf` - Variable definitions
- `provider.tf` - Proxmox provider configuration
- `versions.tf` - Provider version constraints
- `terraform.tfvars` - VM definitions and credentials

## Adding New VMs

Add to the appropriate `terraform.tfvars` file in the cluster directory:
```hcl
kubernetes_vms = [
  # existing VMs...
  {
    name           = "kube07"
    target_node    = "pve1"
    vmid           = 207
    # ... other config
  }
]
```

## State Management

- **tf/elasticsearch/.terraform/**: Elasticsearch state and plugins
- **tf/kubernetes/.terraform/**: Kubernetes state and plugins
- Each directory maintains complete independence