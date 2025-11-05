# Kubespray Kubernetes Cluster Deployment Guide

Complete deployment guide for the production-grade Kubernetes cluster using kubespray with full integration into existing homelab infrastructure.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Infrastructure Provisioning](#infrastructure-provisioning)
5. [Kubespray Configuration](#kubespray-configuration)
6. [Cluster Deployment](#cluster-deployment)
7. [Post-Deployment Verification](#post-deployment-verification)
8. [Platform Components](#platform-components)
9. [Common Issues](#common-issues)

---

## Overview

### Purpose

This kubespray deployment provides a production-grade Kubernetes cluster that offers:
- Full control over cluster components (CNI, storage, ingress)
- Better support for cluster upgrades and maintenance
- Integration with existing Proxmox/Terraform/Ansible infrastructure
- GitOps automation via ArgoCD

### Cluster Topology

**Control Plane Nodes (3):**
- `km01` - Bare metal (192.168.10.234) - 4 cores, 16GB RAM
- `km02` - VM (192.168.10.235) - 4 cores, 8GB RAM
- `km03` - VM (192.168.10.236) - 4 cores, 8GB RAM

**Worker Nodes (3):**
- `kube01` - VM (192.168.10.237) - 8 cores, 16GB RAM
- `kube02` - VM (192.168.10.238) - 8 cores, 16GB RAM
- `kube03` - VM (192.168.10.239) - 8 cores, 16GB RAM

**Key Features:**
- Kubernetes v1.29.5
- Containerd runtime
- Calico CNI
- Distributed etcd (3-member HA)
- CoreDNS + NodeLocal DNS cache
- Cert-manager for internal certificates

---

## Architecture

### Network Architecture

**Physical Network:**
- Node network: `192.168.10.0/24`
- Gateway: `192.168.10.1`
- DNS: `192.168.10.1`
- Domain: `lab.thewortmans.org`

**Cluster Networks:**
- Service network: `10.233.0.0/18`
- Pod network: `10.233.64.0/18`
- MetalLB pool: `192.168.100.0/24`

**IP Allocations:**
- km01: 192.168.10.234 (bare metal)
- km02: 192.168.10.235 (VM on pve1)
- km03: 192.168.10.236 (VM on pve2)
- kube01: 192.168.10.237 (VM on pve3)
- kube02: 192.168.10.238 (VM on pve1)
- kube03: 192.168.10.239 (VM on pve2)

### Component Stack

**Infrastructure Layer:**
- Proxmox VE: Hypervisor (3-node cluster: pve1, pve2, pve3)
- Terraform: Infrastructure provisioning
- HashiCorp Vault: Secrets management (192.168.10.101)

**Cluster Layer:**
- Kubespray: Cluster deployment
- Containerd: Container runtime
- Calico: CNI plugin
- Etcd: Distributed key-value store (3-member cluster)
- CoreDNS: Cluster DNS with NodeLocal cache

**Platform Layer:**
- Democratic CSI: Storage provisioning (FreeNAS iSCSI/NFS)
- MetalLB: LoadBalancer services
- Traefik: Ingress controller
- Cert-manager: Certificate management
- ArgoCD: GitOps automation

---

## Prerequisites

### Infrastructure Requirements

#### Vault Server
- Running and unsealed at `https://192.168.10.101:8200`
- Valid VAULT_TOKEN with read permissions
- Required secrets populated (see below)

Test Vault connectivity:
```bash
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_TOKEN="your-vault-token"
export VAULT_SKIP_VERIFY="true"
vault status
```

#### Proxmox Cluster
- Healthy 3-node cluster (pve1, pve2, pve3)
- Template `ubuntu-25.04` available
- Storage pool `tank` with sufficient space (~1.6TB)
- Network bridge `vmbr0` configured
- IP addresses 192.168.10.235-239 available

#### Bare Metal Node (km01)
- Already configured and accessible
- Ubuntu 25.04 installed
- SSH key authentication configured
- IP: 192.168.10.234

#### Network Infrastructure
- DNS server at 192.168.10.1 operational
- Gateway at 192.168.10.1 accessible
- Domain `lab.thewortmans.org` configured

### Required Secrets in Vault

All credentials must be stored in Vault before deployment.

**Proxmox Credentials:**
```bash
vault kv put secret/homelab/proxmox/terraform \
  username="terraform@pve" \
  password="your-proxmox-password" \
  cipassword="your-cloud-init-password"
```

**FreeNAS Credentials:**
```bash
vault kv put secret/homelab/freenas/credentials \
  api_key="your-api-key" \
  password="your-root-password"

vault kv put secret/homelab/freenas/ssh \
  private_key="$(cat ~/.ssh/freenas_rsa)" \
  public_key="$(cat ~/.ssh/freenas_rsa.pub)"
```

Verify secrets:
```bash
vault kv get secret/homelab/proxmox/terraform
vault kv get secret/homelab/freenas/credentials
```

### Local System Requirements

**Software Tools:**
- Terraform >= 1.0
- Ansible >= 2.12
- Python 3
- kubectl
- Vault CLI

Verify installations:
```bash
terraform version
ansible --version
python3 --version
kubectl version --client
vault version
```

**Kubespray Installation:**
```bash
# Clone kubespray if not already present
git clone https://github.com/kubernetes-sigs/kubespray.git ~/git/kubespray
cd ~/git/kubespray

# Checkout stable version
git checkout release-2.24

# Verify installation
ls ~/git/kubespray/cluster.yml
```

**SSH Configuration:**
- SSH key at `/Users/bret/.ssh/github_rsa`
- Key added to km01 bare metal node
- Test SSH access:
```bash
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.234 hostname
```

### Configuration Files

Verify these files exist:
- `/Users/bret/git/homelab/tf/kubespray/` - Terraform configuration
- `/Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini` - Kubespray inventory
- `/Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/` - Cluster configuration
- `/Users/bret/git/homelab/ansible/playbooks/deploy_kubespray_cluster.yml` - Deployment playbook

---

## Infrastructure Provisioning

### Terraform Directory Structure

```
tf/kubespray/
├── main.tf              # VM resource definitions
├── variables.tf         # Variable declarations
├── outputs.tf           # Output definitions
├── terraform.tfvars     # Variable values
├── versions.tf          # Provider versions
└── README.md           # Terraform documentation
```

### Provision VMs with Terraform

#### 1. Navigate to Terraform Directory

```bash
\cd /Users/bret/git/homelab/tf/kubespray/
```

#### 2. Initialize Terraform

```bash
terraform init
```

Expected output:
```
Initializing the backend...
Initializing provider plugins...
- Finding latest version of telmate/proxmox...
- Finding latest version of hashicorp/vault...
Terraform has been successfully initialized!
```

#### 3. Validate Configuration

```bash
terraform validate
```

Expected output:
```
Success! The configuration is valid.
```

#### 4. Review Deployment Plan

```bash
terraform plan -var-file=terraform.tfvars
```

Review the plan:
- Should show 5 VMs to be created
- Verify VM specifications (cores, RAM, disk)
- Verify IP addresses (192.168.10.235-239)
- Verify Proxmox node distribution (pve1, pve2, pve3)

#### 5. Apply Configuration

```bash
terraform apply -var-file=terraform.tfvars
```

Type `yes` when prompted.

Duration: 5-10 minutes

Expected output:
```
Apply complete! Resources: 5 added, 0 changed, 0 destroyed.

Outputs:

control_plane_hostnames = [
  "km02.lab.thewortmans.org",
  "km03.lab.thewortmans.org",
]
control_plane_ips = [
  "192.168.10.235",
  "192.168.10.236",
]
worker_hostnames = [
  "kube01.lab.thewortmans.org",
  "kube02.lab.thewortmans.org",
  "kube03.lab.thewortmans.org",
]
worker_ips = [
  "192.168.10.237",
  "192.168.10.238",
  "192.168.10.239",
]
```

#### 6. Verify VMs in Proxmox

Check Proxmox Web UI:
- km02 (VMID 221) on pve1 - Running
- km03 (VMID 222) on pve2 - Running
- kube01 (VMID 223) on pve3 - Running
- kube02 (VMID 224) on pve1 - Running
- kube03 (VMID 225) on pve2 - Running

#### 7. Wait for Cloud-Init

Wait 2-3 minutes for cloud-init to complete user setup and SSH key installation.

#### 8. Test SSH Connectivity

```bash
# Test all nodes
for host in 192.168.10.234 192.168.10.235 192.168.10.236 192.168.10.237 192.168.10.238 192.168.10.239; do
  echo "Testing SSH to $host"
  ssh -i /Users/bret/.ssh/github_rsa bret@$host "hostname"
done
```

Expected: Each command returns the hostname.

#### 9. Verify Python Installation

```bash
for host in 192.168.10.234 192.168.10.235 192.168.10.236 192.168.10.237 192.168.10.238 192.168.10.239; do
  echo "Testing Python on $host"
  ssh -i /Users/bret/.ssh/github_rsa bret@$host "python3 --version"
done
```

Expected: Each node reports Python 3.x version.

---

## Kubespray Configuration

### Inventory Structure

```
kubespray/inventory/homelab/
├── hosts.ini                        # Main inventory file
├── README.md                        # Inventory documentation
├── group_vars/
│   ├── all/
│   │   ├── all.yml                 # Common variables
│   │   └── etcd.yml                # Etcd configuration
│   └── k8s_cluster/
│       ├── k8s-cluster.yml         # Main cluster config
│       ├── addons.yml              # Addon selection
│       └── k8s-net-containerd.yml  # Containerd config
└── host_vars/                       # Host-specific overrides
```

### Key Configuration Files

#### hosts.ini

Defines cluster topology and node roles:
- `kube_control_plane` group: km01, km02, km03
- `kube_node` group: kube01, kube02, kube03
- `etcd` group: km01, km02, km03
- All nodes use ansible_user=bret and SSH key authentication

#### k8s-cluster.yml

Main cluster configuration:
- Kubernetes version: v1.29.5
- CNI plugin: Calico
- Service CIDR: 10.233.0.0/18
- Pod CIDR: 10.233.64.0/18
- Container manager: containerd
- DNS mode: coredns
- NodeLocal DNS: enabled

#### addons.yml

Add-on selection:
- Helm: enabled
- Metrics-server: enabled
- Cert-manager: enabled
- MetalLB: disabled (deployed via ArgoCD)
- Ingress-nginx: disabled (using Traefik)

#### etcd.yml

Etcd configuration:
- Deployment type: host (systemd service)
- Data directory: /var/lib/etcd
- Memory limit: 2048M
- Quota backend: 2GB

### Customizing Configuration

To customize the cluster, edit the group_vars files:

```bash
# Edit main cluster config
vi /Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/k8s-cluster.yml

# Edit add-ons
vi /Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/addons.yml
```

See `kubespray/CONFIG-DECISIONS.md` for rationale behind configuration choices.

---

## Cluster Deployment

### Deployment Workflow

The deployment uses an Ansible wrapper playbook that:
1. Performs pre-flight checks
2. Executes kubespray's cluster.yml playbook
3. Performs post-deployment verification

### Deploy Cluster with Kubespray

#### 1. Navigate to Ansible Directory

```bash
\cd /Users/bret/git/homelab/ansible
```

#### 2. Verify Ansible Inventory

```bash
cat /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini
```

Verify:
- All 6 nodes listed
- IP addresses correct
- Groups properly defined
- SSH configuration correct

#### 3. Test Ansible Connectivity

```bash
ansible -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini all -m ping
```

Expected:
```
km01 | SUCCESS => { "ping": "pong" }
km02 | SUCCESS => { "ping": "pong" }
km03 | SUCCESS => { "ping": "pong" }
kube01 | SUCCESS => { "ping": "pong" }
kube02 | SUCCESS => { "ping": "pong" }
kube03 | SUCCESS => { "ping": "pong" }
```

**Do not proceed if any node fails connectivity check.**

#### 4. Run Deployment Playbook

```bash
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/deploy_kubespray_cluster.yml
```

Duration: 30-60 minutes

### Deployment Phases

**Phase 1: Pre-flight Checks (2-5 minutes)**
- Verifying Vault connectivity
- Testing SSH to all nodes
- Displaying deployment plan
- **Prompt: Press ENTER to confirm deployment**

**Phase 2: Download Phase (5-15 minutes)**
- Downloading Kubernetes binaries
- Downloading container images
- Downloading CNI plugins

**Phase 3: Etcd Installation (5-10 minutes)**
- Installing etcd on control plane nodes
- Configuring etcd cluster
- Verifying etcd quorum

**Phase 4: Kubernetes Control Plane (10-20 minutes)**
- Installing kubelet, kubectl, kubeadm
- Bootstrapping first control plane node (km01)
- Joining additional control plane nodes (km02, km03)
- Installing CoreDNS
- Installing Calico CNI

**Phase 5: Worker Nodes (5-10 minutes)**
- Installing kubelet on workers
- Joining workers to cluster

**Phase 6: Add-ons (5-10 minutes)**
- Installing cert-manager
- Installing metrics-server
- Configuring NodeLocal DNS cache

**Phase 7: Post-deployment Verification (2-5 minutes)**
- Checking node status
- Checking pod status
- Verifying etcd health

### Expected Output

```
PLAY RECAP *********************************************************************
km01       : ok=XXX  changed=XXX  unreachable=0    failed=0
km02       : ok=XXX  changed=XXX  unreachable=0    failed=0
km03       : ok=XXX  changed=XXX  unreachable=0    failed=0
kube01     : ok=XXX  changed=XXX  unreachable=0    failed=0
kube02     : ok=XXX  changed=XXX  unreachable=0    failed=0
kube03     : ok=XXX  changed=XXX  unreachable=0    failed=0

======================================
Kubespray Deployment Complete!
======================================

Next steps:
1. Copy kubeconfig from control plane
2. Test cluster access
3. Deploy platform components

See docs/KUBESPRAY-DEPLOYMENT.md for next steps.
======================================
```

---

## Post-Deployment Verification

### Set Up Kubeconfig on km01

SSH to primary control plane:
```bash
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.234
```

Configure kubeconfig:
```bash
mkdir -p ~/.kube
sudo cp /etc/kubernetes/admin.conf ~/.kube/config
sudo chown bret:bret ~/.kube/config
chmod 600 ~/.kube/config
```

### Verify Cluster Health

#### Check Node Status

```bash
kubectl get nodes
```

Expected output:
```
NAME     STATUS   ROLES           AGE   VERSION
km01     Ready    control-plane   10m   v1.29.5
km02     Ready    control-plane   8m    v1.29.5
km03     Ready    control-plane   8m    v1.29.5
kube01   Ready    <none>          5m    v1.29.5
kube02   Ready    <none>          5m    v1.29.5
kube03   Ready    <none>          5m    v1.29.5
```

All nodes should show STATUS=Ready.

#### Check System Pods

```bash
kubectl get pods -A
```

Verify all pods are Running:
- kube-system: calico-node, calico-kube-controllers, coredns, kube-apiserver, kube-controller-manager, kube-scheduler, kube-proxy, nodelocaldns
- cert-manager: cert-manager, cert-manager-cainjector, cert-manager-webhook

#### Verify Etcd Health

```bash
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint health
```

Expected:
```
https://127.0.0.1:2379 is healthy: successfully committed proposal: took = 2.345678ms
```

#### Verify Etcd Members

```bash
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  member list
```

Should show 3 members (km01, km02, km03).

#### Test Cluster Functionality

```bash
# Create test deployment
kubectl create namespace test
kubectl create deployment nginx --image=nginx --replicas=3 -n test
kubectl wait --for=condition=ready pod -l app=nginx -n test --timeout=120s

# Verify pods distributed across nodes
kubectl get pods -n test -o wide

# Clean up
kubectl delete namespace test
```

### Configure Local Kubectl Access

Exit km01 SSH session:
```bash
exit
```

Copy kubeconfig to local machine:
```bash
scp -i /Users/bret/.ssh/github_rsa bret@192.168.10.234:~/.kube/config \
  ~/.kube/config-kubespray
```

Test local access:
```bash
kubectl --kubeconfig ~/.kube/config-kubespray get nodes
```

**Option A: Use dedicated kubeconfig**
```bash
export KUBECONFIG=~/.kube/config-kubespray
kubectl get nodes

# Add to shell profile for persistence
echo 'export KUBECONFIG=~/.kube/config-kubespray' >> ~/.zshrc
```

**Option B: Merge into main kubeconfig**
```bash
cp ~/.kube/config ~/.kube/config.backup-$(date +%Y%m%d-%H%M%S)
KUBECONFIG=~/.kube/config:~/.kube/config-kubespray kubectl config view --flatten > ~/.kube/config-merged
mv ~/.kube/config-merged ~/.kube/config
kubectl config rename-context kubernetes-admin@homelab-kubespray kubespray
kubectl config use-context kubespray
```

---

## Platform Components

After cluster deployment, install platform components in this order:

### 1. Democratic CSI (Storage)

Provides persistent volume provisioning via FreeNAS iSCSI/NFS.

**Prerequisites:**
- Install iSCSI initiator on worker nodes
- Configure FreeNAS datasets and credentials in Vault

**Deployment:**
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/democratic-csi/namespace.yaml

# Deploy iSCSI driver
helm install democratic-csi-iscsi democratic-csi/democratic-csi \
  -n democratic-csi \
  -f /Users/bret/git/homelab/k8s/democratic-csi/values-iscsi.yaml

# Deploy NFS driver
helm install democratic-csi-nfs democratic-csi/democratic-csi \
  -n democratic-csi \
  -f /Users/bret/git/homelab/k8s/democratic-csi/values-nfs.yaml
```

**Verification:**
```bash
kubectl get storageclass
kubectl get pods -n democratic-csi
```

See `/Users/bret/git/homelab/k8s/democratic-csi/README.md` for details.

### 2. MetalLB (LoadBalancer)

Provides LoadBalancer service type for bare metal.

**Deployment:**
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/metallb/namespace.yaml

helm install metallb metallb/metallb \
  -n metallb-system \
  -f /Users/bret/git/homelab/k8s/metallb/values.yaml

# Create IP pool
kubectl apply -f /Users/bret/git/homelab/k8s/metallb/ipaddresspool.yaml
kubectl apply -f /Users/bret/git/homelab/k8s/metallb/l2advertisement.yaml
```

**Verification:**
```bash
kubectl get pods -n metallb-system
kubectl get ipaddresspool -n metallb-system
```

See `/Users/bret/git/homelab/k8s/metallb/README.md` for details.

### 3. Traefik (Ingress)

Provides HTTP/HTTPS ingress routing.

**Deployment:**
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/traefik/namespace.yaml

helm install traefik traefik/traefik \
  -n traefik \
  -f /Users/bret/git/homelab/k8s/traefik/values.yaml
```

**Verification:**
```bash
kubectl get pods -n traefik
kubectl get svc -n traefik
```

See `/Users/bret/git/homelab/k8s/traefik/README.md` for details.

### 4. Cert-Manager Configuration

Configure cert-manager for internal certificates (already installed by kubespray).

**Deployment:**
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/cert-manager/cluster-issuer-selfsigned.yaml
kubectl apply -f /Users/bret/git/homelab/k8s/cert-manager/internal-ca-cert.yaml
kubectl apply -f /Users/bret/git/homelab/k8s/cert-manager/cluster-issuer-ca.yaml
```

**Verification:**
```bash
kubectl get clusterissuer
kubectl get certificate -n cert-manager
```

See `/Users/bret/git/homelab/k8s/cert-manager/README.md` for details.

### 5. ArgoCD (GitOps)

Enables GitOps-based application management.

**Deployment:**
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/argocd/namespace.yaml

helm install argocd argo/argo-cd \
  -n argocd \
  -f /Users/bret/git/homelab/k8s/argocd/values.yaml

# Bootstrap platform apps
kubectl apply -f /Users/bret/git/homelab/k8s/argocd/platform-apps.yaml
```

**Access ArgoCD:**
```bash
# Get admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

# Get LoadBalancer IP
kubectl get svc -n argocd argocd-server

# Access UI: https://<loadbalancer-ip>
```

See `/Users/bret/git/homelab/k8s/argocd/README.md` for details.

---

## Common Issues

### Terraform Issues

**Issue: Vault authentication fails**
```
Error: Error making API request to Vault
```

Solution:
- Verify VAULT_ADDR and VAULT_TOKEN are set
- Check Vault is unsealed: `vault status`
- Verify token permissions: `vault token lookup`

**Issue: Proxmox API connection fails**

Solution:
- Verify Proxmox is accessible: `ping pve1.lab.thewortmans.org`
- Check Vault secrets for Proxmox credentials
- Verify Proxmox API responds: `curl -k https://pve1.lab.thewortmans.org:8006`

**Issue: Template not found**

Solution:
- Verify template exists in Proxmox UI
- Check template name matches exactly (case-sensitive)
- Ensure template on correct storage pool

### Deployment Issues

**Issue: Kubespray download phase fails**

Solution:
- Check internet connectivity on nodes
- Retry playbook (kubespray is idempotent)

**Issue: Etcd fails to start**

Solution:
- SSH to node and check logs: `sudo journalctl -u etcd -xe`
- Common causes: Port conflicts (2379, 2380), time sync issues, firewall

**Issue: Node fails to join cluster**

Solution:
- Check kubelet logs: `sudo journalctl -u kubelet -xe`
- Verify API server accessible from node
- Check certificates are valid

### Post-Deployment Issues

**Issue: Nodes stuck in NotReady**

Solution:
- Check CNI: `kubectl get pods -n kube-system | grep calico`
- Check kubelet logs on node

**Issue: CoreDNS pods CrashLoopBackOff**

Solution:
- Check pod logs: `kubectl logs -n kube-system <coredns-pod>`
- Common cause: CNI not ready

For comprehensive troubleshooting, see `docs/KUBESPRAY-TROUBLESHOOTING.md`.

---

## Next Steps

1. **Deploy Remaining Platform Components**
   - Configure storage classes
   - Deploy monitoring stack
   - Configure backup procedures

2. **Review Operational Documentation**
   - `docs/KUBESPRAY-OPERATIONS.md` - Add/remove nodes, upgrades
   - `docs/KUBESPRAY-BACKUP-RESTORE.md` - Backup and disaster recovery
   - `docs/KUBESPRAY-TROUBLESHOOTING.md` - Detailed troubleshooting

3. **Deploy Applications**
   - Use ArgoCD for GitOps-based deployments
   - Follow existing application patterns in `k8s/` directory

---

## Related Documentation

- **Quick Start**: `docs/KUBESPRAY-QUICKSTART.md` - Fast reference guide
- **Operations**: `docs/KUBESPRAY-OPERATIONS.md` - Day-2 operations
- **Backup/Restore**: `docs/KUBESPRAY-BACKUP-RESTORE.md` - DR procedures
- **Troubleshooting**: `docs/KUBESPRAY-TROUBLESHOOTING.md` - Issue resolution
- **Architecture**: `docs/KUBESPRAY-ARCHITECTURE.md` - Design decisions
- **Configuration**: `docs/KUBESPRAY-CONFIG-REFERENCE.md` - Config reference
- **Config Decisions**: `kubespray/CONFIG-DECISIONS.md` - Rationale

---

*Last Updated: 2025-11-04*
