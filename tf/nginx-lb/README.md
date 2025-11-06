# Nginx Load Balancer HA Cluster

This Terraform configuration provisions a highly available nginx load balancer cluster for Kubernetes API and NodePort service access.

## Architecture

### Two-Node HA Cluster

The cluster consists of two nginx load balancer nodes with Corosync/Pacemaker for high availability:

- **nginx-lb01**: Primary node (192.168.10.251) on pve1
- **nginx-lb02**: Secondary node (192.168.10.252) on pve2
- **Virtual IP (VIP)**: 192.168.10.250 (managed by Pacemaker)

### Network Configuration

| Component | IP Address | Proxmox Host | VMID | Role |
|-----------|------------|--------------|------|------|
| VIP | 192.168.10.250 | N/A (floating) | N/A | Active endpoint |
| nginx-lb01 | 192.168.10.251 | pve1 | 250 | Primary node |
| nginx-lb02 | 192.168.10.252 | pve2 | 251 | Secondary node |

### Deployment Details

**VM Specifications** (per node):
- **Cores**: 2 CPU cores
- **Memory**: 2GB RAM
- **Disk**: 20GB on "tank" NFS storage
- **OS**: Ubuntu 25.04 (cloud-init template)
- **Network**: Static IP on vmbr0 bridge

**Anti-Affinity**:
- nginx-lb01 deployed to pve1
- nginx-lb02 deployed to pve2
- Ensures hypervisor-level HA (survives single Proxmox host failure)

## Dual-Purpose Load Balancing

### Kubernetes API Server (Layer 4)
- **Port**: 6443 (TCP stream/passthrough)
- **Backends**: Control plane nodes km01-03 (192.168.10.234-236)
- **Mode**: TCP passthrough (no SSL termination)
- **Algorithm**: least_conn
- **Health Checks**: max_fails=2, fail_timeout=30s

### NodePort Services (Layer 7)
- **Ports**: Standard HTTP/HTTPS (80, 443) and custom ports (8080, 8443)
- **Backends**: Worker nodes kube01-03 (192.168.10.237-239)
- **Mode**: HTTP/HTTPS proxy with header forwarding
- **Services**: ArgoCD, Traefik, and extensible for additional NodePort services
- **Algorithm**: least_conn
- **Health Checks**: max_fails=2, fail_timeout=30s

## Prerequisites

Before deploying this infrastructure, ensure you have:

1. **HashiCorp Vault** configured with secrets:
   - `secret/homelab/proxmox/terraform` - Proxmox API credentials
   - `secret/homelab/ssh/public_keys` - SSH public keys for cloud-init

2. **Proxmox Environment**:
   - Two or more Proxmox hosts (pve1, pve2) available
   - Ubuntu 25.04 cloud-init template installed
   - "tank" NFS storage available
   - VMIDs 250 and 251 available

3. **Environment Variables**:
   ```bash
   export VAULT_ADDR="https://vault.example.com:8200"
   export VAULT_TOKEN="your-vault-token"
   export VAULT_SKIP_VERIFY="true"  # If using self-signed certs
   ```

## Deployment Procedure

### Step 1: Initialize Terraform

```bash
cd /Users/bret/git/homelab/tf/nginx-lb
terraform init
```

### Step 2: Review Configuration

Verify the configuration in `terraform.tfvars`:
- Two VMs defined in `nginx_lb_vms` array
- Correct IP addresses (251, 252)
- Different target_nodes for anti-affinity (pve1, pve2)
- VIP set to 192.168.10.250

### Step 3: Validate Configuration

```bash
terraform validate
```

### Step 4: Plan Deployment

```bash
terraform plan -var-file=terraform.tfvars
```

Review the plan output to confirm:
- 2 VMs will be created
- nginx-lb01 on pve1 with IP 192.168.10.251
- nginx-lb02 on pve2 with IP 192.168.10.252
- VMIDs are 250 and 251
- Tags are "nginx;loadbalancer;ha"

### Step 5: Run Validation Tests

Execute the test script to validate the configuration:

```bash
chmod +x test-terraform.sh
./test-terraform.sh
```

All 8 tests should pass before proceeding to deployment.

### Step 6: Apply Configuration

```bash
terraform apply -var-file=terraform.tfvars
```

Review the execution plan and type `yes` to confirm.

### Step 7: Verify Deployment

Check the deployment summary:

```bash
terraform output deployment_summary
```

Test SSH connectivity to both nodes:

```bash
ssh bret@192.168.10.251
ssh bret@192.168.10.252
```

## Post-Deployment

After successful VM provisioning, proceed with:

1. **Ansible Inventory Configuration** (Task Group 3)
   - Create `[nginx_lb]` inventory group
   - Configure group variables

2. **Nginx and Corosync Configuration** (Task Group 4)
   - Install nginx on both nodes
   - Configure dual-purpose load balancing
   - Set up Corosync/Pacemaker HA cluster
   - Configure VIP resource

3. **Kubeconfig Updates** (Task Group 5)
   - Update kubeconfig to use VIP (192.168.10.250:6443)
   - Test kubectl operations through load balancer

## Terraform Commands

### View Current State

```bash
terraform show
terraform state list
```

### View Outputs

```bash
terraform output                    # All outputs
terraform output cluster_vip        # Specific output
terraform output ansible_inventory  # Ansible inventory format
```

### Update Configuration

After modifying `terraform.tfvars` or other files:

```bash
terraform plan -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

### Destroy Infrastructure

**WARNING**: This will destroy both VMs. Use with caution.

```bash
terraform destroy -var-file=terraform.tfvars
```

## Troubleshooting

### VM Creation Fails

1. Check Proxmox API connectivity:
   ```bash
   vault kv get secret/homelab/proxmox/terraform
   ```

2. Verify template exists:
   - Log into Proxmox UI
   - Check that "ubuntu-25.04" template exists

3. Verify storage availability:
   - Ensure "tank" NFS storage is mounted
   - Check available space

### SSH Connectivity Issues

1. Check cloud-init logs on the VM:
   ```bash
   # From Proxmox host
   qm guest exec 250 -- cat /var/log/cloud-init.log
   ```

2. Verify SSH keys in Vault:
   ```bash
   vault kv get secret/homelab/ssh/public_keys
   ```

3. Check VM IP configuration:
   ```bash
   # From Proxmox host
   qm guest exec 250 -- ip addr show
   ```

### Anti-Affinity Violations

If both VMs are deployed to the same Proxmox host:

1. Check `terraform.tfvars` configuration
2. Verify `target_node` is set correctly (pve1, pve2)
3. Re-run `terraform plan` to verify placement

## HA Configuration Details

### Failover Behavior

- **Automatic Failover**: VIP moves to secondary when primary fails
- **Failback**: VIP returns to primary when recovered (automatic failback enabled)
- **Failover Time**: < 30 seconds (target)
- **Quorum Policy**: two_node=1 (2-node cluster operation)

### STONITH Configuration

STONITH (Shoot The Other Node In The Head) is **disabled** for this homelab deployment:
- Acceptable for controlled homelab environment
- Reduces complexity
- two_node quorum policy provides sufficient split-brain protection

### Cluster Management

After Ansible configuration (Task Group 4), manage the cluster using:

```bash
# Check cluster status
ssh bret@192.168.10.251 "sudo crm status"

# View VIP resource
ssh bret@192.168.10.251 "sudo crm resource status"

# Manual failover (if needed)
ssh bret@192.168.10.251 "sudo crm resource move cluster-vip nginx-lb02"
```

## Integration with Kubernetes

### API Server Access

After deployment and configuration, Kubernetes API will be accessible via:
- **Endpoint**: https://192.168.10.250:6443
- **Backend**: km01-03 (192.168.10.234-236)
- **Certificate**: Direct to API servers (no termination)

### NodePort Services

NodePort services will be accessible via:
- **HTTP**: http://192.168.10.250
- **HTTPS**: https://192.168.10.250
- **ArgoCD**: http://192.168.10.250:8080, https://192.168.10.250:8443
- **Backends**: kube01-03 (192.168.10.237-239)

## Files in This Directory

- `main.tf` - VM provisioning using count-based iteration
- `variables.tf` - Variable definitions with validation rules
- `terraform.tfvars` - VM configurations and cluster settings
- `outputs.tf` - Cluster information and Ansible inventory format
- `provider.tf` - Proxmox and Vault provider configuration
- `versions.tf` - Terraform version constraints
- `test-terraform.sh` - Validation test suite (8 tests)
- `README.md` - This documentation

## References

- **Spec**: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/spec.md`
- **Requirements**: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/planning/requirements.md`
- **Tasks**: `/Users/bret/git/homelab/agent-os/specs/2025-11-05-nginx-lb-ha/tasks.md`
- **Infrastructure Pattern**: `/Users/bret/git/homelab/tf/kubernetes/` (similar count-based pattern)

## Support

For issues or questions:
1. Review the troubleshooting section above
2. Check Proxmox and Vault logs
3. Verify prerequisite configurations
4. Consult the specification documents in `agent-os/specs/2025-11-05-nginx-lb-ha/`
