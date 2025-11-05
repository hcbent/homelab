# Kubespray Cluster Quick Start Guide

Fast reference for deploying the kubespray Kubernetes cluster. For detailed explanations, see `KUBESPRAY-DEPLOYMENT.md`.

## Prerequisites Checklist

- [ ] Vault running at https://192.168.10.101:8200
- [ ] VAULT_TOKEN set with read permissions
- [ ] Proxmox cluster healthy (pve1, pve2, pve3)
- [ ] Template `ubuntu-25.04` exists
- [ ] IPs 192.168.10.235-239 available
- [ ] SSH key at `/Users/bret/.ssh/github_rsa`
- [ ] SSH access to km01 (192.168.10.234)
- [ ] Terraform, Ansible, kubectl installed
- [ ] Kubespray cloned at `~/git/kubespray`

## Quick Deployment Steps

### 1. Set Environment Variables

```bash
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_TOKEN="your-vault-token-here"
export VAULT_SKIP_VERIFY="true"
```

### 2. Verify Prerequisites

```bash
# Test Vault
vault status

# Test SSH to km01
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.234 hostname

# Verify tools
terraform version
ansible --version
kubectl version --client
```

### 3. Provision VMs with Terraform

```bash
\cd /Users/bret/git/homelab/tf/kubespray/

# Initialize Terraform
terraform init

# Review plan
terraform plan -var-file=terraform.tfvars

# Apply (creates 5 VMs)
terraform apply -var-file=terraform.tfvars
```

**Expected Output:**
```
Apply complete! Resources: 5 added, 0 changed, 0 destroyed.

Outputs:
control_plane_ips = ["192.168.10.235", "192.168.10.236"]
worker_ips = ["192.168.10.237", "192.168.10.238", "192.168.10.239"]
```

**Wait 2-3 minutes for cloud-init to complete.**

### 4. Verify SSH Connectivity

```bash
# Test all nodes
for host in 192.168.10.234 192.168.10.235 192.168.10.236 192.168.10.237 192.168.10.238 192.168.10.239; do
  ssh -i /Users/bret/.ssh/github_rsa bret@$host "hostname"
done
```

**Expected:** Each command returns hostname (km01, km02, km03, kube01, kube02, kube03)

### 5. Deploy Cluster with Kubespray

```bash
\cd /Users/bret/git/homelab/ansible

# Test Ansible connectivity
ansible -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini all -m ping

# Deploy cluster (30-60 minutes)
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/deploy_kubespray_cluster.yml
```

**Expected:** All tasks complete successfully, no failed hosts.

### 6. Verify Cluster Health

```bash
# SSH to km01
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.234

# Set up kubeconfig
mkdir -p ~/.kube
sudo cp /etc/kubernetes/admin.conf ~/.kube/config
sudo chown bret:bret ~/.kube/config

# Check nodes
kubectl get nodes
```

**Expected Output:**
```
NAME     STATUS   ROLES           AGE   VERSION
km01     Ready    control-plane   10m   v1.29.5
km02     Ready    control-plane   8m    v1.29.5
km03     Ready    control-plane   8m    v1.29.5
kube01   Ready    <none>          5m    v1.29.5
kube02   Ready    <none>          5m    v1.29.5
kube03   Ready    <none>          5m    v1.29.5
```

### 7. Check System Pods

```bash
kubectl get pods -A
```

**Expected:** All pods in Running state.

### 8. Verify Etcd Health

```bash
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint health
```

**Expected:** `https://127.0.0.1:2379 is healthy`

### 9. Set Up Local Kubectl Access

```bash
# Exit km01
exit

# Copy kubeconfig to local machine
scp -i /Users/bret/.ssh/github_rsa bret@192.168.10.234:~/.kube/config \
  ~/.kube/config-kubespray

# Test local access
kubectl --kubeconfig ~/.kube/config-kubespray get nodes

# Set environment variable
export KUBECONFIG=~/.kube/config-kubespray

# Add to shell profile
echo 'export KUBECONFIG=~/.kube/config-kubespray' >> ~/.zshrc
```

### 10. Deploy Platform Components

```bash
# 1. Democratic CSI (Storage)
kubectl apply -f /Users/bret/git/homelab/k8s/democratic-csi/namespace.yaml
# Follow k8s/democratic-csi/README.md for Helm deployment

# 2. MetalLB (LoadBalancer)
kubectl apply -f /Users/bret/git/homelab/k8s/metallb/namespace.yaml
# Follow k8s/metallb/README.md for Helm deployment

# 3. Traefik (Ingress)
kubectl apply -f /Users/bret/git/homelab/k8s/traefik/namespace.yaml
# Follow k8s/traefik/README.md for Helm deployment

# 4. Cert-manager configuration
kubectl apply -f /Users/bret/git/homelab/k8s/cert-manager/cluster-issuer-selfsigned.yaml
kubectl apply -f /Users/bret/git/homelab/k8s/cert-manager/internal-ca-cert.yaml
kubectl apply -f /Users/bret/git/homelab/k8s/cert-manager/cluster-issuer-ca.yaml

# 5. ArgoCD (GitOps)
kubectl apply -f /Users/bret/git/homelab/k8s/argocd/namespace.yaml
# Follow k8s/argocd/README.md for Helm deployment
```

## Verification Commands

### Cluster Status

```bash
# All nodes ready
kubectl get nodes

# All pods running
kubectl get pods -A

# Storage classes available
kubectl get storageclass

# Cluster info
kubectl cluster-info
```

### Component Status

```bash
# Democratic CSI
kubectl get pods -n democratic-csi

# MetalLB
kubectl get pods -n metallb-system
kubectl get ipaddresspool -n metallb-system

# Traefik
kubectl get pods -n traefik
kubectl get svc -n traefik

# Cert-manager
kubectl get pods -n cert-manager
kubectl get clusterissuer

# ArgoCD
kubectl get pods -n argocd
kubectl get applications -n argocd
```

### Etcd Health

```bash
# From km01
ssh bret@192.168.10.234

# Check health
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint health

# List members
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  member list
```

**Expected:** 3 healthy members (km01, km02, km03)

## Common Issues

### Terraform: Vault authentication fails
```bash
# Verify Vault access
vault status
vault token lookup

# Re-export token
export VAULT_TOKEN="your-token-here"
```

### Terraform: VMs fail to create
```bash
# Check Proxmox connectivity
ping pve1.lab.thewortmans.org

# Verify template exists
# Check in Proxmox UI or:
ssh root@pve1 "qm list"
```

### SSH connectivity fails
```bash
# Wait for cloud-init (2-3 minutes)
# Check VM console in Proxmox
# Verify SSH service on VM
```

### Ansible: Ping fails
```bash
# Verify inventory file
cat /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini

# Test SSH manually
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.235
```

### Deployment: Download fails
```bash
# Check internet connectivity on nodes
# Retry playbook (idempotent)
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/deploy_kubespray_cluster.yml
```

### Nodes not Ready
```bash
# Check CNI pods
kubectl get pods -n kube-system | grep calico

# Check kubelet logs on node
ssh bret@192.168.10.237
sudo journalctl -u kubelet -f
```

### Pods CrashLoopBackOff
```bash
# Check pod logs
kubectl logs -n <namespace> <pod-name>

# Describe pod for events
kubectl describe pod -n <namespace> <pod-name>
```

## Quick Reference

### Network Configuration
- Node network: 192.168.10.0/24
- Service CIDR: 10.233.0.0/18
- Pod CIDR: 10.233.64.0/18
- MetalLB pool: 192.168.100.0/24

### Node IPs
- km01: 192.168.10.234 (bare metal)
- km02: 192.168.10.235 (VM)
- km03: 192.168.10.236 (VM)
- kube01: 192.168.10.237 (VM)
- kube02: 192.168.10.238 (VM)
- kube03: 192.168.10.239 (VM)

### Vault Paths
- Proxmox: `secret/homelab/proxmox/terraform`
- FreeNAS: `secret/homelab/freenas/credentials`

### File Locations
- Terraform: `/Users/bret/git/homelab/tf/kubespray/`
- Inventory: `/Users/bret/git/homelab/kubespray/inventory/homelab/`
- Playbooks: `/Users/bret/git/homelab/ansible/playbooks/`
- K8s manifests: `/Users/bret/git/homelab/k8s/`

### Important Commands

```bash
# Terraform
\cd /Users/bret/git/homelab/tf/kubespray/
terraform init
terraform plan -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
terraform destroy -var-file=terraform.tfvars

# Ansible
\cd /Users/bret/git/homelab/ansible
ansible -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini all -m ping
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini playbooks/deploy_kubespray_cluster.yml

# Kubectl
kubectl get nodes
kubectl get pods -A
kubectl get storageclass
kubectl cluster-info
```

## Next Steps

After successful deployment:

1. **Deploy monitoring stack** (Prometheus, Grafana)
2. **Configure backups** - See `docs/KUBESPRAY-BACKUP-RESTORE.md`
3. **Deploy applications** via ArgoCD
4. **Set up monitoring** and alerting

## Detailed Documentation

For comprehensive information, see:
- **Full Deployment Guide**: `docs/KUBESPRAY-DEPLOYMENT.md`
- **Operations**: `docs/KUBESPRAY-OPERATIONS.md`
- **Backup/Restore**: `docs/KUBESPRAY-BACKUP-RESTORE.md`
- **Troubleshooting**: `docs/KUBESPRAY-TROUBLESHOOTING.md`
- **Architecture**: `docs/KUBESPRAY-ARCHITECTURE.md`

---

*Last Updated: 2025-11-04*
