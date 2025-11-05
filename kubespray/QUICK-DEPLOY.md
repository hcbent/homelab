# Kubespray Quick Deployment Guide

This is the fastest path to deploying your kubespray Kubernetes cluster.

## Prerequisites

### Setup Ansible Virtual Environment

Kubespray requires Ansible < 2.18.0. If you have a newer version, create a virtual environment:

```bash
cd ~/git/kubespray
./setup-ansible-venv.sh
source ~/git/kubespray/venv/bin/activate
```

**Note:** Keep this environment activated for all kubespray commands.

### Run Pre-flight Checks

Before deployment, run the pre-flight checks:

```bash
cd /Users/bret/git/homelab/ansible
ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini playbooks/kubespray_preflight.yml
```

## Deployment Steps

### Step 1: Provision VMs with Terraform

```bash
# Set Vault token
export VAULT_TOKEN=$(vault login -token-only)

# Navigate to terraform directory
cd /Users/bret/git/homelab/tf/kubespray

# Provision VMs
terraform init
terraform plan
terraform apply
```

**Expected Output:** 5 VMs created (km02, km03, kube01, kube02, kube03)

### Step 2: Deploy Kubernetes Cluster

**IMPORTANT:** Run kubespray from its own directory to avoid role path issues:

```bash
cd ~/git/kubespray
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini cluster.yml
```

**Duration:** 30-60 minutes

**What's happening:**
- Pre-flight checks
- Package installation
- Etcd cluster setup (3 nodes)
- Control plane deployment
- Worker node joining
- CNI (Calico) installation
- Add-ons (CoreDNS, metrics-server, cert-manager)

### Step 3: Verify Deployment

After deployment completes, verify the cluster:

```bash
# SSH to primary control plane
ssh bret@192.168.10.234

# Check nodes
kubectl get nodes

# Check pods
kubectl get pods -A

# Check etcd health
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint health
```

**Expected:**
- All 6 nodes in Ready state
- All system pods Running
- Etcd shows 3 healthy members

### Step 4: Get Kubeconfig Locally

```bash
# Copy kubeconfig from km01
scp bret@192.168.10.234:~/.kube/config ~/.kube/config-kubespray

# Test access
kubectl --kubeconfig ~/.kube/config-kubespray get nodes
```

## Next Steps

After the cluster is deployed:

1. **Deploy Storage (Democratic CSI)**
   ```bash
   cd /Users/bret/git/homelab/k8s/democratic-csi
   # Follow README.md
   ```

2. **Deploy MetalLB**
   ```bash
   cd /Users/bret/git/homelab/k8s/metallb
   # Follow README.md
   ```

3. **Deploy Traefik**
   ```bash
   cd /Users/bret/git/homelab/k8s/traefik
   # Follow README.md
   ```

4. **Deploy ArgoCD (for GitOps)**
   ```bash
   cd /Users/bret/git/homelab/k8s/argocd
   # Follow README.md
   ```

## Troubleshooting

If deployment fails:

1. **Check logs on control plane:**
   ```bash
   ssh bret@192.168.10.234
   sudo journalctl -xeu kubelet
   ```

2. **Check Ansible logs:**
   Look for errors in the ansible-playbook output

3. **Verify SSH access:**
   ```bash
   ansible all -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini -m ping
   ```

4. **Check detailed troubleshooting:**
   See `/Users/bret/git/homelab/docs/KUBESPRAY-TROUBLESHOOTING.md`

## Full Documentation

For complete documentation, see:
- Deployment guide: `docs/KUBESPRAY-DEPLOYMENT.md`
- Operations: `docs/KUBESPRAY-OPERATIONS.md`
- Backup/Restore: `docs/KUBESPRAY-BACKUP-RESTORE.md`
- Architecture: `docs/KUBESPRAY-ARCHITECTURE.md`
