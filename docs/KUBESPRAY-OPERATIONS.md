# Kubespray Cluster Operations Guide

Operational procedures for day-2 management of the kubespray Kubernetes cluster including node management, upgrades, and maintenance tasks.

## Table of Contents

1. [Adding Nodes](#adding-nodes)
2. [Removing Nodes](#removing-nodes)
3. [Cluster Upgrades](#cluster-upgrades)
4. [Cluster Health Checks](#cluster-health-checks)
5. [Common Maintenance Tasks](#common-maintenance-tasks)

---

## Adding Nodes

### Adding Control Plane Nodes

Control plane nodes run the Kubernetes API server, scheduler, controller-manager, and etcd. Adding control plane nodes increases cluster availability and etcd quorum size.

**Important:** Etcd requires an odd number of members (3, 5, 7). Adding one control plane node gives you a 4-member etcd cluster, which is less fault-tolerant than 3 or 5 members. Consider adding 2 nodes to reach 5 members.

#### Prerequisites

- Vault access for retrieving Proxmox credentials (if provisioning VM)
- SSH access to new node(s)
- Sufficient resources on Proxmox cluster (if VM)
- Available IP addresses in 192.168.10.0/24 range

#### Step 1: Provision New VM (if VM-based)

If adding a VM control plane node:

```bash
\cd /Users/bret/git/homelab/tf/kubespray/

# Edit main.tf to add new VM resource
# Example: km04 with VMID 226, IP 192.168.10.240

# Add to main.tf:
resource "proxmox_vm_qemu" "km04" {
  name        = "km04"
  target_node = "pve3"
  vmid        = 226
  clone       = "ubuntu-25.04"

  cores   = 4
  memory  = 8192
  scsihw  = "virtio-scsi-single"

  disk {
    size    = "100G"
    type    = "scsi"
    storage = "tank"
  }

  network {
    model  = "virtio"
    bridge = "vmbr0"
  }

  ipconfig0 = "ip=192.168.10.240/24,gw=192.168.10.1"

  ciuser     = "bret"
  cipassword = data.vault_generic_secret.proxmox.data["cipassword"]
  sshkeys    = file("~/.ssh/github_rsa.pub")
}

# Apply Terraform
terraform plan -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

Wait 2-3 minutes for cloud-init to complete, then verify SSH:
```bash
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.240 hostname
```

#### Step 2: Update Kubespray Inventory

Edit inventory file:
```bash
vi /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini
```

Add new node to appropriate groups:
```ini
[all]
km01 ansible_host=192.168.10.234
km02 ansible_host=192.168.10.235
km03 ansible_host=192.168.10.236
km04 ansible_host=192.168.10.240  # NEW NODE
kube01 ansible_host=192.168.10.237
kube02 ansible_host=192.168.10.238
kube03 ansible_host=192.168.10.239

[kube_control_plane]
km01
km02
km03
km04  # NEW NODE

[etcd]
km01
km02
km03
km04  # NEW NODE

[kube_node]
kube01
kube02
kube03

[k8s_cluster:children]
kube_control_plane
kube_node
```

#### Step 3: Run Node Addition Playbook

```bash
\cd /Users/bret/git/homelab/ansible

# Test connectivity
ansible -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini km04 -m ping

# Add node to cluster
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/add_kubespray_node.yml
```

Duration: 15-30 minutes

#### Step 4: Verify Node Joined Cluster

```bash
# Check nodes
kubectl get nodes

# Verify etcd members (should now show 4 members)
ssh bret@192.168.10.234
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  member list
```

Expected: 4 etcd members shown.

#### Step 5: Label New Node

```bash
kubectl label node km04 node-role.kubernetes.io/control-plane=""
kubectl get nodes --show-labels
```

**Considerations:**
- **4-member etcd**: Can tolerate 1 failure (quorum = 3)
- **5-member etcd**: Can tolerate 2 failures (quorum = 3) - more resilient
- Consider adding a 5th control plane node for better HA

---

### Adding Worker Nodes

Worker nodes run application workloads. You can add as many workers as needed.

#### Step 1: Provision New VM (if VM-based)

```bash
\cd /Users/bret/git/homelab/tf/kubespray/

# Edit main.tf to add new VM
# Example: kube04 with VMID 227, IP 192.168.10.241

# Add to main.tf:
resource "proxmox_vm_qemu" "kube04" {
  name        = "kube04"
  target_node = "pve1"
  vmid        = 227
  clone       = "ubuntu-25.04"

  cores   = 8
  memory  = 16384
  scsihw  = "virtio-scsi-single"

  disk {
    size    = "200G"
    type    = "scsi"
    storage = "tank"
  }

  network {
    model  = "virtio"
    bridge = "vmbr0"
  }

  ipconfig0 = "ip=192.168.10.241/24,gw=192.168.10.1"

  ciuser     = "bret"
  cipassword = data.vault_generic_secret.proxmox.data["cipassword"]
  sshkeys    = file("~/.ssh/github_rsa.pub")
}

# Apply Terraform
terraform apply -var-file=terraform.tfvars
```

Verify SSH access:
```bash
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.241 hostname
```

#### Step 2: Update Inventory

Edit inventory file:
```bash
vi /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini
```

Add to `[all]` and `[kube_node]` groups:
```ini
[all]
km01 ansible_host=192.168.10.234
km02 ansible_host=192.168.10.235
km03 ansible_host=192.168.10.236
kube01 ansible_host=192.168.10.237
kube02 ansible_host=192.168.10.238
kube03 ansible_host=192.168.10.239
kube04 ansible_host=192.168.10.241  # NEW NODE

[kube_node]
kube01
kube02
kube03
kube04  # NEW NODE
```

#### Step 3: Install iSCSI Initiator (for storage)

If using Democratic CSI with iSCSI:

```bash
ssh -i /Users/bret/.ssh/github_rsa bret@192.168.10.241

sudo apt-get update
sudo apt-get install -y open-iscsi
sudo systemctl enable --now iscsid
sudo systemctl status iscsid

exit
```

#### Step 4: Run Node Addition Playbook

```bash
\cd /Users/bret/git/homelab/ansible

ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/add_kubespray_node.yml
```

Duration: 10-20 minutes

#### Step 5: Verify and Label

```bash
# Check node joined
kubectl get nodes

# Label as worker
kubectl label node kube04 node-role.kubernetes.io/worker=""

# Verify pods can schedule on new node
kubectl get pods -A -o wide | grep kube04
```

---

## Removing Nodes

### Removing Worker Nodes

Safely remove a worker node from the cluster.

#### Step 1: Cordon Node

Prevent new pods from scheduling on the node:
```bash
kubectl cordon kube03
```

#### Step 2: Drain Node

Evict all pods from the node:
```bash
kubectl drain kube03 \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --force \
  --timeout=300s
```

This will:
- Delete pods (except DaemonSets)
- Move workloads to other nodes
- Respect PodDisruptionBudgets

Monitor pod migration:
```bash
watch kubectl get pods -A -o wide
```

#### Step 3: Delete Node from Cluster

```bash
kubectl delete node kube03
```

#### Step 4: Update Inventory

Remove node from inventory file:
```bash
vi /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini

# Remove kube03 from [all] and [kube_node] groups
```

#### Step 5: Destroy VM (if VM-based)

```bash
\cd /Users/bret/git/homelab/tf/kubespray/

# Option A: Remove resource from main.tf and apply
# Edit main.tf to remove kube03 resource
terraform apply -var-file=terraform.tfvars

# Option B: Targeted destroy
terraform destroy -target=proxmox_vm_qemu.kube03 -var-file=terraform.tfvars
```

---

### Removing Control Plane Nodes

**Warning:** Removing control plane nodes affects etcd quorum. Be extremely careful.

**Important:** Never remove enough control plane nodes to lose etcd quorum:
- 3-member cluster: Can safely remove 1 node (leaves 2, quorum still possible)
- 5-member cluster: Can safely remove 2 nodes (leaves 3, quorum still possible)

#### Prerequisites

- At least one other healthy control plane node will remain
- Etcd quorum will be maintained after removal

#### Step 1: Verify Current Etcd Members

```bash
ssh bret@192.168.10.234

sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  member list
```

Note the member ID of the node to be removed.

#### Step 2: Remove Etcd Member

From a healthy control plane node:

```bash
# Get member ID of node to remove (e.g., km03)
MEMBER_ID=$(sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  member list | grep km03 | cut -d',' -f1)

# Remove member
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  member remove $MEMBER_ID
```

#### Step 3: Cordon and Drain

```bash
kubectl cordon km03
kubectl drain km03 --ignore-daemonsets --delete-emptydir-data
```

#### Step 4: Delete Node

```bash
kubectl delete node km03
```

#### Step 5: Update Inventory

Remove from inventory:
```bash
vi /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini

# Remove km03 from [all], [kube_control_plane], and [etcd] groups
```

#### Step 6: Clean Up Node (optional)

SSH to the node and clean up Kubernetes:
```bash
ssh bret@192.168.10.236

sudo kubeadm reset -f
sudo rm -rf /etc/kubernetes /var/lib/etcd /var/lib/kubelet /etc/cni

exit
```

#### Step 7: Destroy VM

```bash
\cd /Users/bret/git/homelab/tf/kubespray/
terraform destroy -target=proxmox_vm_qemu.km03 -var-file=terraform.tfvars
```

---

## Cluster Upgrades

### Kubernetes Version Upgrades

Upgrade Kubernetes to a newer version using kubespray.

**Important:**
- Only upgrade one minor version at a time (e.g., 1.29 → 1.30)
- Review Kubernetes and kubespray release notes
- **Always backup etcd before upgrading** (see KUBESPRAY-BACKUP-RESTORE.md)

#### Step 1: Review Release Notes

Check for breaking changes:
- Kubernetes release notes: https://kubernetes.io/releases/
- Kubespray release notes: https://github.com/kubernetes-sigs/kubespray/releases

#### Step 2: Backup Etcd

**CRITICAL:** Always backup etcd before upgrading.

```bash
ssh bret@192.168.10.234

sudo ETCDCTL_API=3 etcdctl snapshot save /tmp/etcd-backup-pre-upgrade-$(date +%Y%m%d-%H%M%S).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem

# Copy to safe location
scp /tmp/etcd-backup-*.db bret@backup-server:/backups/
```

See `KUBESPRAY-BACKUP-RESTORE.md` for detailed backup procedures.

#### Step 3: Update Kubespray

```bash
\cd ~/git/kubespray

# Check current version
git describe --tags

# Fetch latest
git fetch --all --tags

# Checkout new version (e.g., upgrade to 2.25)
git checkout release-2.25
```

#### Step 4: Update Cluster Configuration

Edit group_vars to set new Kubernetes version:

```bash
vi /Users/bret/git/homelab/kubespray/inventory/homelab/group_vars/k8s_cluster/k8s-cluster.yml

# Change:
kube_version: v1.30.0  # or whatever version you're upgrading to
```

#### Step 5: Run Upgrade Playbook

```bash
\cd /Users/bret/git/homelab/ansible

ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/upgrade_kubespray_cluster.yml
```

Duration: 30-90 minutes

The upgrade will:
1. Backup etcd on all control plane nodes
2. Upgrade control plane nodes one by one
3. Upgrade worker nodes one by one
4. Verify cluster health after each node

#### Step 6: Verify Upgrade

```bash
# Check node versions
kubectl get nodes

# Check component versions
kubectl get pods -n kube-system -o yaml | grep "image:" | sort -u

# Check cluster health
kubectl get componentstatuses
kubectl get pods -A

# Verify etcd
ssh bret@192.168.10.234
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint health
```

#### Post-Upgrade Checklist

- [ ] All nodes show new version: `kubectl get nodes`
- [ ] All pods running: `kubectl get pods -A`
- [ ] Etcd healthy: Check endpoint health
- [ ] Test application functionality
- [ ] Monitor for issues over next 24 hours

---

## Cluster Health Checks

Regular health checks to ensure cluster is operating correctly.

### Node Health

```bash
# Check node status
kubectl get nodes

# Check node conditions
kubectl describe nodes | grep -A 5 "Conditions:"

# Check node resource usage
kubectl top nodes
```

**Healthy nodes show:**
- STATUS: Ready
- Conditions: Ready=True, MemoryPressure=False, DiskPressure=False, PIDPressure=False

### Pod Health

```bash
# Check all pods
kubectl get pods -A

# Check for problematic pods
kubectl get pods -A --field-selector status.phase!=Running

# Check pod resource usage
kubectl top pods -A
```

### Etcd Health

```bash
ssh bret@192.168.10.234

# Check etcd endpoint health
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://192.168.10.234:2379,https://192.168.10.235:2379,https://192.168.10.236:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint health

# Check etcd member list
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  member list

# Check etcd database size
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint status --write-out=table
```

### Component Health

```bash
# API server
kubectl get --raw='/healthz?verbose'

# Scheduler and controller-manager
kubectl get pods -n kube-system | grep -E "kube-scheduler|kube-controller-manager"

# CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Calico
kubectl get pods -n kube-system -l k8s-app=calico-node
kubectl get pods -n kube-system -l k8s-app=calico-kube-controllers
```

### Storage Health

```bash
# Check storage classes
kubectl get storageclass

# Check PVs and PVCs
kubectl get pv
kubectl get pvc -A

# Check CSI drivers
kubectl get pods -n democratic-csi
kubectl get csidrivers
```

### Network Health

```bash
# Test service connectivity
kubectl run test-pod --image=nicolaka/netshoot --rm -it -- /bin/bash

# Inside pod:
# Test DNS
nslookup kubernetes.default
nslookup google.com

# Test service connectivity
curl -I kubernetes.default.svc.cluster.local

exit

# Check NetworkPolicies (if any)
kubectl get networkpolicies -A

# Check endpoints
kubectl get endpoints -A
```

---

## Common Maintenance Tasks

### Restart Cluster Components

#### Restart kubelet on a node

```bash
ssh bret@kube01
sudo systemctl restart kubelet
sudo systemctl status kubelet
```

#### Restart containerd on a node

```bash
ssh bret@kube01
sudo systemctl restart containerd
sudo systemctl status containerd
```

#### Restart a specific pod

```bash
# Delete pod (will be recreated by controller)
kubectl delete pod -n kube-system <pod-name>

# Or restart deployment
kubectl rollout restart deployment -n <namespace> <deployment-name>
```

### Certificate Rotation

Kubernetes certificates are auto-rotated by kubelet. To manually rotate:

```bash
ssh bret@km01

# Check certificate expiration
sudo kubeadm certs check-expiration

# Renew certificates (if needed)
sudo kubeadm certs renew all

# Restart control plane components
sudo systemctl restart kubelet
```

### Etcd Database Compaction

As etcd accumulates revisions, the database grows. Compact periodically.

```bash
ssh bret@192.168.10.234

# Get current revision
REV=$(sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint status --write-out="json" | jq -r '.[0].Status.header.revision')

echo "Current revision: $REV"

# Compact (retain last 1000 revisions)
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  compact $((REV - 1000))

# Defragment (must do on each member)
for endpoint in 192.168.10.234:2379 192.168.10.235:2379 192.168.10.236:2379; do
  echo "Defragmenting $endpoint"
  sudo ETCDCTL_API=3 etcdctl \
    --endpoints=https://$endpoint \
    --cacert=/etc/ssl/etcd/ssl/ca.pem \
    --cert=/etc/ssl/etcd/ssl/node-km01.pem \
    --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
    defrag
done
```

### Node Reboots

When rebooting nodes, always drain first:

```bash
# Drain node
kubectl drain kube01 --ignore-daemonsets --delete-emptydir-data

# Reboot
ssh bret@kube01
sudo reboot

# Wait for node to come back up
# Uncordon node
kubectl uncordon kube01

# Verify node ready
kubectl get nodes
```

### Updating Calico/CNI Configuration

To update Calico configuration:

```bash
# Edit Calico ConfigMap
kubectl edit configmap -n kube-system calico-config

# Restart Calico pods
kubectl delete pod -n kube-system -l k8s-app=calico-node

# Verify Calico healthy
kubectl get pods -n kube-system -l k8s-app=calico-node
```

---

## Related Documentation

- **Deployment**: `docs/KUBESPRAY-DEPLOYMENT.md`
- **Backup/Restore**: `docs/KUBESPRAY-BACKUP-RESTORE.md`
- **Troubleshooting**: `docs/KUBESPRAY-TROUBLESHOOTING.md`
- **Architecture**: `docs/KUBESPRAY-ARCHITECTURE.md`
- **Configuration**: `docs/KUBESPRAY-CONFIG-REFERENCE.md`

---

*Last Updated: 2025-11-04*
