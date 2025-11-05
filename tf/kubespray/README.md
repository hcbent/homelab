# Kubespray Kubernetes Cluster Infrastructure

This Terraform configuration provisions the VMs required for deploying a production-grade Kubernetes cluster using kubespray.

## Overview

This configuration creates **5 VMs** across the Proxmox cluster:
- **2 Control Plane VMs**: km02, km03 (4 cores, 8GB RAM, 100GB disk)
- **3 Worker VMs**: kube01, kube02, kube03 (8 cores, 16GB RAM, 200GB disk)

**Note**: km01 (192.168.10.234) is a **bare metal** control plane node and is NOT provisioned by Terraform. It is included in the kubespray inventory but managed separately.

## Architecture

### Node Distribution
VMs are distributed across the Proxmox cluster for high availability:
- **pve1**: km02, kube02
- **pve2**: km03, kube03
- **pve3**: kube01

### Network Configuration
- **Network**: 192.168.10.0/24
- **Gateway**: 192.168.10.1
- **DNS**: 192.168.10.1
- **Domain**: lab.thewortmans.org

### IP Allocations
| Node   | IP Address       | Type          | Role          | Etcd |
|--------|------------------|---------------|---------------|------|
| km01   | 192.168.10.234   | Bare Metal    | Control Plane | Yes  |
| km02   | 192.168.10.235   | VM (pve1)     | Control Plane | Yes  |
| km03   | 192.168.10.236   | VM (pve2)     | Control Plane | Yes  |
| kube01 | 192.168.10.237   | VM (pve3)     | Worker        | No   |
| kube02 | 192.168.10.238   | VM (pve1)     | Worker        | No   |
| kube03 | 192.168.10.239   | VM (pve2)     | Worker        | No   |

### VM Specifications

**Control Plane VMs (km02, km03)**:
- CPU: 4 cores, 1 socket
- Memory: 8GB (8192 MB)
- Disk: 100GB on "tank" storage
- Template: ubuntu-25.04
- Network: vmbr0 bridge

**Worker VMs (kube01-kube03)**:
- CPU: 8 cores, 1 socket
- Memory: 16GB (16384 MB)
- Disk: 200GB on "tank" storage
- Template: ubuntu-25.04
- Network: vmbr0 bridge

## Prerequisites

### 1. Vault Setup
Ensure HashiCorp Vault is running and accessible at `https://192.168.10.101:8200`

Required secrets in Vault:
```bash
# Proxmox API credentials
vault kv put secret/homelab/proxmox/terraform \
  username="terraform@pve" \
  password="your-proxmox-password" \
  ciuser="bret" \
  cipassword="your-cloud-init-password"
```

### 2. Vault Authentication
Set your Vault token:
```bash
export VAULT_TOKEN=$(vault login -token-only)
```

### 3. Proxmox Configuration
- Proxmox cluster with nodes: pve1, pve2, pve3
- Ubuntu 25.04 cloud-init template: `ubuntu-25.04`
- NFS storage pool: `tank`
- Network bridge: `vmbr0`

### 4. Configuration File
Copy the example configuration:
```bash
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` and update:
- `sshkeys` - Your SSH public key
- Any custom VM specifications if needed

## Usage

### Initialize Terraform
```bash
terraform init
```

### Validate Configuration
```bash
terraform validate
```

### Preview Changes
```bash
terraform plan
```

This will show you the 5 VMs that will be created with their complete specifications.

### Apply Configuration
```bash
terraform apply
```

**IMPORTANT**: Review the plan carefully before confirming. This will:
- Create 5 new VMs across the Proxmox cluster
- Configure cloud-init with SSH keys and network settings
- Allocate static IP addresses
- Start the VMs automatically

Expected execution time: 5-10 minutes

### View Outputs
After applying, view the inventory information:
```bash
terraform output
```

Outputs include:
- `all_nodes` - All cluster nodes for kubespray inventory
- `control_plane_vms` - Control plane VM details
- `worker_vms` - Worker VM details
- `control_plane_ips` - All control plane IPs (including km01)
- `worker_ips` - All worker IPs
- `etcd_nodes` - Nodes running etcd (all control plane)

### Destroy Infrastructure
**⚠️ WARNING**: This will destroy all provisioned VMs
```bash
terraform destroy
```

## Post-Provisioning Steps

### 1. Verify SSH Access
Test SSH connectivity to all provisioned VMs:
```bash
ssh bret@192.168.10.235  # km02
ssh bret@192.168.10.236  # km03
ssh bret@192.168.10.237  # kube01
ssh bret@192.168.10.238  # kube02
ssh bret@192.168.10.239  # kube03
```

### 2. Wait for Cloud-Init
Cloud-init may take a few minutes to complete on first boot. Check status:
```bash
ssh bret@192.168.10.235 'cloud-init status'
```

### 3. Generate Kubespray Inventory
Use the Terraform outputs to generate the kubespray inventory file:
```bash
terraform output -json all_nodes > /tmp/terraform-nodes.json
# Use this to populate kubespray/inventory/homelab/hosts.yml
```

### 4. Deploy Kubernetes Cluster
Once VMs are provisioned and accessible, proceed to deploy the cluster using kubespray:
```bash
cd /Users/bret/git/homelab/ansible/
ansible-playbook deploy_kubespray_cluster.yml
```

## Troubleshooting

### Vault Connection Issues
```bash
# Test Vault connectivity
curl -k https://192.168.10.101:8200/v1/sys/health

# Verify Vault token
vault token lookup

# Re-authenticate if needed
export VAULT_TOKEN=$(vault login -token-only)
```

### Proxmox API Issues
```bash
# Test Proxmox API access (replace with your credentials)
curl -k https://pve1.lab.thewortmans.org:8006/api2/json/access/ticket \
  -d "username=terraform@pve&password=your-password"
```

### VM Creation Failures
Check Proxmox logs:
```bash
ssh root@pve1.lab.thewortmans.org 'tail -f /var/log/pve/tasks/active'
```

Common issues:
- Template `ubuntu-25.04` not found - Verify template exists on all Proxmox nodes
- Storage `tank` not available - Verify NFS storage is mounted
- IP address conflicts - Ensure IPs 192.168.10.235-239 are not in use
- VMID conflicts - Ensure VMIDs 221-225 are not in use

### Cloud-Init Not Working
If VMs don't get network configuration:
1. Verify template has cloud-init installed
2. Check cloud-init logs: `ssh bret@<vm-ip> 'sudo cat /var/log/cloud-init.log'`
3. Verify vmbr0 bridge configuration on Proxmox nodes

## Maintenance

### Adding More Worker Nodes
1. Edit `terraform.tfvars`
2. Add new VM entries to `worker_vms` list:
```hcl
  {
    name           = "kube04"
    target_node    = "pve3"
    vmid           = "226"
    # ... rest of configuration
    ipconfig0      = "ip=192.168.10.240/24,gw=192.168.10.1"
  }
```
3. Run `terraform apply`
4. Update kubespray inventory
5. Run `ansible-playbook add_kubespray_node.yml`

### Adding More Control Plane Nodes
**IMPORTANT**: Always maintain an odd number of control plane nodes (3, 5, 7) for etcd quorum.

Follow the same process as adding workers, but add to `control_plane_vms` list.

### Updating VM Specifications
Due to the `lifecycle.prevent_destroy = true` setting in the module, you cannot:
- Change VMID
- Change clone source
- Change certain disk/network settings without destroying the VM

For major changes, you'll need to:
1. Drain the node in Kubernetes
2. Remove from kubespray inventory
3. Run `terraform destroy -target=module.worker_vms[index]`
4. Update configuration
5. Run `terraform apply`
6. Add back to kubespray inventory

## Security Notes

- Proxmox credentials are stored in Vault, never in git
- Cloud-init passwords are stored in Vault
- SSH key-based authentication is enforced
- All communication with Proxmox uses HTTPS (with self-signed certs)
- VMs have `prevent_destroy` lifecycle policy to prevent accidental deletion

## Integration with Kubespray

This Terraform configuration is designed to work seamlessly with kubespray:

1. **Terraform** provisions the VMs
2. **Terraform outputs** provide data for kubespray inventory
3. **Kubespray** deploys Kubernetes on the provisioned VMs
4. **Ansible wrapper playbooks** orchestrate the deployment

See `/Users/bret/git/homelab/docs/KUBESPRAY-DEPLOYMENT.md` for complete deployment documentation.

## Files

- `main.tf` - VM module instantiation for control plane and worker nodes
- `variables.tf` - Variable definitions
- `provider.tf` - Proxmox and Vault provider configuration with Vault integration
- `versions.tf` - Provider version constraints
- `outputs.tf` - Outputs for kubespray inventory generation
- `terraform.tfvars` - VM definitions and configuration (not in git)
- `terraform.tfvars.example` - Example configuration template
- `README.md` - This file

## References

- Proxmox VM Module: `../modules/proxmox_vm/`
- Kubespray Configuration: `/Users/bret/git/homelab/kubespray/`
- Ansible Playbooks: `/Users/bret/git/homelab/ansible/`
- Vault Documentation: `/Users/bret/git/homelab/docs/VAULT-SETUP.md`
