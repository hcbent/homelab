# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Architecture

This is a Terraform-based homelab infrastructure management repository organized into specialized deployment environments. The repository uses a multi-environment approach where each major infrastructure component is managed through separate Terraform configurations with independent state files.

### Directory Structure

- **`tf/lab/`**: Elasticsearch cluster infrastructure (9 VMs: es01-es09)
- **`tf/kubernetes/`**: Kubernetes cluster infrastructure (6 VMs: kube01-kube06)
- **`tf/home-apps/`**: Home application infrastructure (media servers, NAS, etc.)
- **`tf/modules/proxmox_vm/`**: Reusable Terraform module for Proxmox VM provisioning
- **`tf/monitoring/`**: Monitoring infrastructure (currently empty)

Each environment directory contains:
- `main.tf` - VM module instantiation
- `terraform.tfvars` - VM definitions, credentials, and networking
- `variables.tf` - Variable definitions
- `provider.tf` - Proxmox provider configuration
- `versions.tf` - Provider version constraints

### Core Infrastructure Components

The infrastructure targets three main clusters:

1. **Elasticsearch Cluster** (`tf/lab/`): 9-node Elasticsearch deployment
   - es01-es06: Data nodes (4 cores, 8GB RAM, 1TB storage)
   - es07-es09: Master nodes (lighter specs for coordination)
   - Network: 192.168.10.31-39 range

2. **Kubernetes Cluster** (`tf/kubernetes/`): 6-node K8s deployment
   - kube01-kube03: Control plane nodes (2 cores, 2GB RAM)
   - kube04-kube06: Worker nodes (4 cores, 8GB RAM)
   - Network: 192.168.10.11-16 range

3. **Home Applications** (`tf/home-apps/`): Media and utility servers
   - plex: Media server (4 cores, 32GB RAM, high storage)
   - Additional home services as needed

## Terraform Operations

### Environment-Specific Deployment

Each environment operates independently with separate state files to prevent cross-environment interference:

```bash
# Elasticsearch cluster
cd tf/lab/
terraform init
terraform plan
terraform apply

# Kubernetes cluster
cd tf/kubernetes/
terraform init
terraform plan
terraform apply

# Home applications
cd tf/home-apps/
terraform init
terraform plan
terraform apply
```

### VM Configuration Management

VMs are defined in each environment's `terraform.tfvars` file with the following structure:

```hcl
# For elasticsearch cluster (tf/lab/)
elasticsearch_vms = [
  {
    name           = "es01"
    target_node    = "pve1"
    vmid           = "301"
    clone          = "ubuntu-25.04"
    cores          = "4"
    memory         = "8192"
    disk_size      = "1024G"
    disk_storage   = "tank"
    ipconfig0      = "ip=192.168.10.31/24,gw=192.168.10.1"
    # ... other parameters
  }
]

# For kubernetes cluster (tf/kubernetes/)
kubernetes_vms = [
  {
    name           = "kube01"
    target_node    = "pve1"
    vmid           = 201
    cores          = 2
    memory         = 2048
    disk_size      = "100G"
    # ... other parameters
  }
]

# For home applications (tf/home-apps/)
home_app_vms = [
  {
    name           = "plex"
    target_node    = "pve1"
    vmid           = 101
    cores          = 4
    memory         = 32768
    # ... other parameters
  }
]
```

### Adding New VMs

Use the provided helper script for VM configuration templates:

```bash
./add-vm.sh <vm-name> [vmid] [cores] [memory] [disk-size]
# Example: ./add-vm.sh kube07 207 4 8192 200G
```

Then add the generated configuration to the appropriate `terraform.tfvars` file in the target environment.

## Proxmox VM Module

The shared `modules/proxmox_vm/` module provides standardized VM provisioning with:

### Standard Configuration
- **OS**: Ubuntu 25.04 cloud-init template cloning
- **Storage**: "tank" NFS storage backend
- **Network**: virtio model on vmbr0 bridge
- **Domain**: lab.thewortmans.org with 192.168.10.1 DNS
- **Authentication**: Cloud-init with SSH key deployment

### Resource Lifecycle Management
- **Prevent Destroy**: VMs protected from accidental destruction
- **Ignore Changes**: Extensive ignore_changes list prevents unnecessary replacements
- **Serial Console**: Configured for Proxmox web console compatibility

### Default Resource Allocations
- **Cores**: 2 CPU cores
- **Memory**: 2GB RAM
- **Storage**: 10GB disk on "tank" storage
- **Network**: DHCP (override with ipconfig0 for static IPs)

## Network and Storage Architecture

### IP Address Ranges
- **Kubernetes**: 192.168.10.11-16 (kube01-kube06)
- **Elasticsearch**: 192.168.10.31-39 (es01-es09)
- **Home Apps**: 192.168.10.101+ (plex, etc.)
- **Gateway**: 192.168.10.1
- **DNS**: 192.168.10.1

### Storage Configuration
- **Primary Storage**: "tank" NFS share (referenced as `disk_storage = "tank"`)
- **Template Storage**: Ubuntu 25.04 cloud-init images
- **Disk Sizing**: Environment-specific (100G for K8s nodes, 1TB for ES data nodes)

## Security and Access

### Authentication Methods
- **Proxmox**: root@pam authentication for provider
- **VM Access**: Cloud-init with SSH public key deployment
- **Default User**: "bret" with sudo privileges

### Network Security
- **Domain**: lab.thewortmans.org internal domain
- **DNS Resolution**: Internal DNS server at 192.168.10.1
- **SSH Access**: Key-based authentication only

## Development Workflow

### State Management Best Practices
1. Always work within the specific environment directory
2. Never mix tfvars files between environments
3. Each environment maintains independent .terraform/ state
4. Use `terraform plan` before any apply operations

### Common Development Tasks

```bash
# Check current state of environment
terraform show

# Import existing VM (if needed)
terraform import 'module.proxmox_vms[0].proxmox_vm_qemu.vm' <node>/<vmid>

# Validate configuration
terraform validate

# Format code
terraform fmt -recursive
```

### VM Lifecycle Operations

```bash
# Plan changes for specific environment
cd tf/kubernetes/
terraform plan

# Apply only specific resources
terraform apply -target='module.proxmox_vms[0]'

# Destroy specific VM (use with caution)
terraform destroy -target='module.proxmox_vms[0]'
```