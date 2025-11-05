# Kubespray Cluster Backup and Restore Guide

Comprehensive backup and disaster recovery procedures for the kubespray Kubernetes cluster.

## Table of Contents

1. [Backup Procedures](#backup-procedures)
2. [Restore Procedures](#restore-procedures)
3. [Disaster Recovery Scenarios](#disaster-recovery-scenarios)

---

## Backup Procedures

### Etcd Backup

Etcd is the critical component storing all cluster state. Regular backups are essential.

#### Manual Etcd Backup

Perform from any control plane node:

```bash
ssh bret@192.168.10.234

# Create backup directory
sudo mkdir -p /var/backups/etcd

# Create snapshot
sudo ETCDCTL_API=3 etcdctl snapshot save \
  /var/backups/etcd/etcd-snapshot-$(date +%Y%m%d-%H%M%S).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem

# Verify snapshot
sudo ETCDCTL_API=3 etcdctl snapshot status \
  /var/backups/etcd/etcd-snapshot-$(date +%Y%m%d-%H%M%S).db \
  --write-out=table
```

#### Copy Backup to External Storage

```bash
# Copy to local machine
scp bret@192.168.10.234:/var/backups/etcd/etcd-snapshot-*.db ~/backups/

# Or copy to NAS
ssh bret@192.168.10.234
sudo scp /var/backups/etcd/etcd-snapshot-*.db user@nas:/volume1/backups/k8s/
```

#### Automated Etcd Backup

Create a cron job for daily backups:

```bash
ssh bret@192.168.10.234

# Create backup script
sudo tee /usr/local/bin/backup-etcd.sh << 'EOF'
#!/bin/bash
set -e

BACKUP_DIR="/var/backups/etcd"
BACKUP_FILE="${BACKUP_DIR}/etcd-snapshot-$(date +%Y%m%d-%H%M%S).db"
REMOTE_BACKUP="/mnt/nas/backups/k8s"

# Create backup
ETCDCTL_API=3 etcdctl snapshot save ${BACKUP_FILE} \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-$(hostname).pem \
  --key=/etc/ssl/etcd/ssl/node-$(hostname)-key.pem

# Verify backup
ETCDCTL_API=3 etcdctl snapshot status ${BACKUP_FILE}

# Copy to NAS (if mounted)
if [ -d "${REMOTE_BACKUP}" ]; then
  cp ${BACKUP_FILE} ${REMOTE_BACKUP}/
fi

# Keep only last 7 days locally
find ${BACKUP_DIR} -name "etcd-snapshot-*.db" -mtime +7 -delete

echo "Backup completed: ${BACKUP_FILE}"
EOF

sudo chmod +x /usr/local/bin/backup-etcd.sh

# Add cron job (daily at 2 AM)
sudo crontab -e
# Add line:
0 2 * * * /usr/local/bin/backup-etcd.sh >> /var/log/etcd-backup.log 2>&1
```

#### Verify Automated Backups

```bash
# Test backup script
sudo /usr/local/bin/backup-etcd.sh

# Check cron job
sudo crontab -l

# Check backup log
sudo tail -f /var/log/etcd-backup.log

# List backups
ls -lh /var/backups/etcd/
```

---

### Cluster Configuration Backup

Back up all configuration files and manifests.

#### Kubespray Configuration

All kubespray configuration is in Git:

```bash
\cd /Users/bret/git/homelab

# Ensure all changes committed
git status

# Create backup tag
git tag -a backup-$(date +%Y%m%d-%H%M%S) -m "Pre-maintenance backup"

# Push to remote
git push origin --tags

# Create archive backup
tar czf ~/backups/homelab-config-$(date +%Y%m%d-%H%M%S).tar.gz \
  kubespray/ \
  ansible/ \
  k8s/ \
  tf/
```

#### Kubernetes Resources

Backup all Kubernetes resources:

```bash
# Backup all resources in all namespaces
kubectl get all --all-namespaces -o yaml > ~/backups/k8s-all-resources-$(date +%Y%m%d-%H%M%S).yaml

# Backup specific namespaces
for ns in argocd democratic-csi metallb-system traefik cert-manager; do
  kubectl get all,configmap,secret,ingress,pvc,pv -n $ns -o yaml > ~/backups/k8s-ns-${ns}-$(date +%Y%m%d-%H%M%S).yaml
done

# Backup cluster-wide resources
kubectl get clusterrole,clusterrolebinding,storageclass,clusterissuer -o yaml > ~/backups/k8s-cluster-resources-$(date +%Y%m%d-%H%M%S).yaml
```

#### Terraform State Backup

```bash
\cd /Users/bret/git/homelab/tf/kubespray

# Backup state file
cp terraform.tfstate ~/backups/terraform-kubespray-state-$(date +%Y%m%d-%H%M%S).tfstate

# Backup state to Terraform Cloud/remote backend (if configured)
terraform state pull > ~/backups/terraform-kubespray-state-$(date +%Y%m%d-%H%M%S).tfstate
```

---

### Application State Backup

#### Persistent Volume Backups

For applications with PVs, use volume snapshots or backup tools.

**Option A: CSI Snapshots (if supported by Democratic CSI)**

```bash
# Create VolumeSnapshot
kubectl apply -f - <<EOF
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: app-snapshot-$(date +%Y%m%d-%H%M%S)
  namespace: default
spec:
  volumeSnapshotClassName: csi-snapshot-class
  source:
    persistentVolumeClaimName: my-app-pvc
EOF

# List snapshots
kubectl get volumesnapshots -A
```

**Option B: FreeNAS ZFS Snapshots**

Create snapshots on FreeNAS directly:

```bash
# SSH to FreeNAS
ssh root@freenas

# List datasets
zfs list

# Create snapshot
zfs snapshot tank/k8s/volumes@backup-$(date +%Y%m%d-%H%M%S)

# List snapshots
zfs list -t snapshot tank/k8s/volumes
```

**Option C: Velero Backup (if installed)**

```bash
# Backup namespace
velero backup create ns-backup --include-namespaces argocd

# Backup entire cluster
velero backup create full-backup

# List backups
velero backup get
```

---

## Restore Procedures

### Etcd Restore

**WARNING:** This is a destructive operation. Only perform during disaster recovery.

#### Prerequisites

- Access to etcd backup file
- All control plane nodes accessible
- Cluster must be stopped before restore

#### Step 1: Stop Cluster

Stop Kubernetes on all nodes:

```bash
# On each control plane node (km01, km02, km03)
ssh bret@192.168.10.234
sudo systemctl stop kubelet
sudo systemctl stop etcd

# Repeat for km02, km03
```

#### Step 2: Backup Current State

Before restoring, backup current state (if any):

```bash
ssh bret@192.168.10.234
sudo mv /var/lib/etcd /var/lib/etcd.old.$(date +%Y%m%d-%H%M%S)
```

#### Step 3: Restore Etcd Snapshot

Restore on each control plane node:

```bash
# On km01
ssh bret@192.168.10.234

# Copy backup file to node (if not already there)
scp ~/backups/etcd-snapshot-20251104-120000.db bret@192.168.10.234:/tmp/

# Restore snapshot
sudo ETCDCTL_API=3 etcdctl snapshot restore /tmp/etcd-snapshot-20251104-120000.db \
  --name=etcd1 \
  --initial-cluster=etcd1=https://192.168.10.234:2380,etcd2=https://192.168.10.235:2380,etcd3=https://192.168.10.236:2380 \
  --initial-cluster-token=etcd-cluster-token \
  --initial-advertise-peer-urls=https://192.168.10.234:2380 \
  --data-dir=/var/lib/etcd

# Fix permissions
sudo chown -R etcd:etcd /var/lib/etcd
```

Repeat for km02 (change name to etcd2, IP to 235) and km03 (name etcd3, IP 236).

#### Step 4: Start Etcd

Start etcd on all control plane nodes:

```bash
# On each control plane node
sudo systemctl start etcd
sudo systemctl status etcd
```

Verify etcd cluster:

```bash
ssh bret@192.168.10.234

sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  member list
```

Should show 3 members.

#### Step 5: Start Kubernetes

```bash
# On each control plane node
sudo systemctl start kubelet

# On all worker nodes
sudo systemctl start kubelet
```

#### Step 6: Verify Cluster

```bash
kubectl get nodes
kubectl get pods -A
kubectl get namespaces
```

---

### Cluster Rebuild from Configuration

Complete cluster rebuild from backed-up configuration.

#### Prerequisites

- Backed-up kubespray configuration (Git repository)
- Backed-up Terraform state
- Backed-up etcd snapshot (optional, for state recovery)
- Access to Vault with all secrets

#### Step 1: Restore Configuration Files

```bash
\cd /Users/bret/git/homelab

# If using Git
git checkout <backup-tag>

# Or restore from archive
tar xzf ~/backups/homelab-config-20251104-120000.tar.gz -C /Users/bret/git/homelab/
```

#### Step 2: Restore Terraform State (if VMs still exist)

```bash
\cd /Users/bret/git/homelab/tf/kubespray

# Restore state file
cp ~/backups/terraform-kubespray-state-20251104-120000.tfstate terraform.tfstate

# Refresh state
terraform refresh -var-file=terraform.tfvars
```

#### Step 3: Provision Infrastructure (if VMs destroyed)

```bash
\cd /Users/bret/git/homelab/tf/kubespray

# Provision new VMs
terraform init
terraform apply -var-file=terraform.tfvars
```

Wait for cloud-init to complete on all VMs.

#### Step 4: Deploy Kubernetes

```bash
\cd /Users/bret/git/homelab/ansible

# Verify connectivity
ansible -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini all -m ping

# Deploy cluster
ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
  playbooks/deploy_kubespray_cluster.yml
```

#### Step 5: Restore Etcd State (optional)

If you want to restore cluster state from backup:

```bash
# Follow "Etcd Restore" procedure above
```

Otherwise, you'll have a fresh cluster and need to redeploy applications.

#### Step 6: Restore Applications

```bash
# Apply backed-up resource manifests
kubectl apply -f ~/backups/k8s-all-resources-20251104-120000.yaml

# Or use ArgoCD to sync applications
kubectl apply -f /Users/bret/git/homelab/k8s/argocd/platform-apps.yaml
```

---

## Disaster Recovery Scenarios

### Scenario 1: Single Control Plane Node Failure

**Situation:** One control plane node (e.g., km02) fails.

**Impact:**
- Cluster continues operating (etcd quorum maintained: 2 of 3)
- API server, scheduler, controller-manager redundancy maintained
- No immediate action required

**Recovery:**

```bash
# Verify cluster health
kubectl get nodes
# km02 will show NotReady

# Check etcd quorum
ssh bret@192.168.10.234
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://192.168.10.234:2379,https://192.168.10.236:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint health
# Two endpoints should be healthy

# If node can be repaired
ssh bret@192.168.10.235
sudo systemctl start etcd
sudo systemctl start kubelet

# If node must be replaced
# Follow "Removing Control Plane Nodes" then "Adding Control Plane Nodes" in KUBESPRAY-OPERATIONS.md
```

---

### Scenario 2: Etcd Quorum Loss

**Situation:** Two or more control plane nodes fail (etcd quorum lost).

**Impact:**
- Cluster enters read-only mode
- No new pods can be scheduled
- Existing pods continue running
- **CRITICAL**: Immediate action required

**Recovery:**

#### Option A: Restore Failed Nodes

If nodes can be quickly restored:

```bash
# Fix and restart nodes
ssh bret@192.168.10.235
sudo systemctl restart etcd
sudo systemctl restart kubelet

# Verify etcd quorum restored
ssh bret@192.168.10.234
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://192.168.10.234:2379,https://192.168.10.235:2379,https://192.168.10.236:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint health
```

#### Option B: Restore from Backup

If nodes cannot be restored:

1. Follow "Etcd Restore" procedure above
2. Restore snapshot to all control plane nodes
3. Restart cluster

---

### Scenario 3: Complete Cluster Failure

**Situation:** All control plane and worker nodes fail or become inaccessible.

**Impact:**
- Complete cluster outage
- All workloads down
- Full restore required

**Recovery:**

1. **Provision new infrastructure** (if hardware failed):
   ```bash
   \cd /Users/bret/git/homelab/tf/kubespray
   terraform apply -var-file=terraform.tfvars
   ```

2. **Deploy new cluster**:
   ```bash
   \cd /Users/bret/git/homelab/ansible
   ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini \
     playbooks/deploy_kubespray_cluster.yml
   ```

3. **Restore etcd from backup**:
   - Follow "Etcd Restore" procedure
   - Use most recent backup

4. **Verify cluster state**:
   ```bash
   kubectl get nodes
   kubectl get namespaces
   kubectl get pods -A
   ```

5. **Restore applications** (if not in etcd backup):
   ```bash
   kubectl apply -f ~/backups/k8s-all-resources-<date>.yaml
   ```

---

### Scenario 4: Data Center Outage

**Situation:** All Proxmox hosts down, entire homelab offline.

**Impact:**
- Complete infrastructure outage
- VMs powered off
- Full restore required when power returns

**Recovery:**

1. **Wait for infrastructure to return**:
   - Proxmox cluster comes online
   - VMs auto-start (if configured)

2. **Verify VM status**:
   ```bash
   # Check Proxmox UI or:
   ssh root@pve1 "qm list"
   ```

3. **Start VMs manually** (if needed):
   ```bash
   ssh root@pve1
   qm start 221  # km02
   qm start 223  # kube01
   qm start 224  # kube02
   ```

4. **Verify cluster comes up**:
   ```bash
   # Wait 5-10 minutes for all services to start
   kubectl get nodes
   kubectl get pods -A
   ```

5. **Check etcd health**:
   ```bash
   ssh bret@192.168.10.234
   sudo ETCDCTL_API=3 etcdctl endpoint health \
     --endpoints=https://192.168.10.234:2379,https://192.168.10.235:2379,https://192.168.10.236:2379 \
     --cacert=/etc/ssl/etcd/ssl/ca.pem \
     --cert=/etc/ssl/etcd/ssl/node-km01.pem \
     --key=/etc/ssl/etcd/ssl/node-km01-key.pem
   ```

6. **Check application status**:
   ```bash
   kubectl get pods -A

   # Restart any crashlooping pods
   kubectl delete pod -n <namespace> <pod-name>
   ```

---

## Backup Best Practices

### Frequency

- **Etcd**: Daily automated backups, keep 7 days locally, 30 days on NAS
- **Configuration**: After every significant change, via Git commits
- **Application State**: Weekly or before major changes

### Storage

- **Local**: `/var/backups/etcd` on control plane nodes
- **NAS**: `/volume1/backups/k8s` on FreeNAS
- **Off-site**: Cloud storage (S3, Google Drive) for critical backups

### Testing

- **Monthly**: Test etcd restore procedure on test cluster
- **Quarterly**: Full disaster recovery drill
- **After Major Changes**: Verify backups immediately

### Automation

- **Cron jobs**: Automated etcd backups
- **Git hooks**: Automatic config commits
- **Monitoring**: Alert on backup failures

---

## Related Documentation

- **Deployment**: `docs/KUBESPRAY-DEPLOYMENT.md`
- **Operations**: `docs/KUBESPRAY-OPERATIONS.md`
- **Troubleshooting**: `docs/KUBESPRAY-TROUBLESHOOTING.md`
- **Architecture**: `docs/KUBESPRAY-ARCHITECTURE.md`

---

*Last Updated: 2025-11-04*
