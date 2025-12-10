# Disaster Recovery Runbook

This runbook provides step-by-step instructions for recovering the Kubernetes cluster from a complete disaster using Velero backups stored on MinIO (Synology NAS).

## Disaster Scenarios Covered

1. **Complete cluster failure** - All nodes lost
2. **Control plane failure** - k3s server node lost
3. **Storage failure** - TrueNAS data loss
4. **Accidental cluster deletion** - ArgoCD prune or kubectl mishap

## Prerequisites for Recovery

### Infrastructure Requirements

- [ ] At least one server/VM for k3s control plane
- [ ] Network connectivity to:
  - MinIO on Synology NAS (192.168.1.230:9000)
  - TrueNAS for iSCSI storage (truenas.lab.thewortmans.org)
- [ ] MinIO credentials (access key and secret key)
- [ ] SSH access to servers

### Software Requirements

- k3s installation script or binary
- kubectl CLI
- velero CLI (`brew install velero` or download from GitHub)
- Helm (for reinstalling ArgoCD)

## Phase 1: Restore Cluster Infrastructure

### Step 1.1: Install k3s on Control Plane Node

```bash
# Install k3s as server (single node or first node of HA cluster)
curl -sfL https://get.k3s.io | sh -s - server \
  --cluster-init \
  --disable traefik

# Wait for k3s to be ready
sudo k3s kubectl get nodes

# Copy kubeconfig for local access
sudo cat /etc/rancher/k3s/k3s.yaml > ~/.kube/config
chmod 600 ~/.kube/config
```

### Step 1.2: (Optional) Restore k3s from etcd Snapshot

If you have an etcd snapshot from before the disaster:

```bash
# List available etcd snapshots (if TrueNAS is available)
ls /var/lib/rancher/k3s/server/db/snapshots/

# Or copy snapshot from backup location
scp backup-server:/backups/k3s-etcd-snapshot-YYYYMMDD.db /tmp/

# Restore from snapshot
sudo k3s server \
  --cluster-reset \
  --cluster-reset-restore-path=/tmp/etcd-snapshot-YYYYMMDD.db
```

### Step 1.3: Join Worker Nodes (if applicable)

```bash
# Get join token from server node
sudo cat /var/lib/rancher/k3s/server/node-token

# On worker nodes:
curl -sfL https://get.k3s.io | K3S_URL=https://<server-ip>:6443 \
  K3S_TOKEN=<token> sh -
```

### Step 1.4: Verify Cluster Health

```bash
kubectl get nodes
kubectl get pods -A
```

## Phase 2: Restore Core Services

### Step 2.1: Install ArgoCD

```bash
# Create argocd namespace
kubectl create namespace argocd

# Install ArgoCD
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Or use local manifest if available
kubectl apply -f /path/to/k8s/install-argocd.yaml

# Wait for ArgoCD to be ready
kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s

# Get initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

### Step 2.2: Restore democratic-csi for Storage

```bash
# Apply democratic-csi ArgoCD application
kubectl apply -f /path/to/k8s/democratic-csi-app.yaml

# Or manually install via Helm
helm repo add democratic-csi https://democratic-csi.github.io/charts/
helm install democratic-csi democratic-csi/democratic-csi \
  -n democratic-csi --create-namespace \
  -f /path/to/k8s/democratic-csi/values-iscsi.yaml

# Verify storage class is available
kubectl get storageclass
```

### Step 2.3: Install MetalLB (for LoadBalancer services)

```bash
# Apply MetalLB configuration
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.13.12/config/manifests/metallb-native.yaml

# Wait for controller
kubectl wait --for=condition=available deployment/controller -n metallb-system --timeout=120s

# Apply IP pool configuration (from your manifests)
kubectl apply -f /path/to/k8s/metallb-config.yaml
```

## Phase 3: Install and Configure Velero

### Step 3.1: Install Velero CLI

```bash
# macOS
brew install velero

# Linux
wget https://github.com/vmware-tanzu/velero/releases/download/v1.14.0/velero-v1.14.0-linux-amd64.tar.gz
tar -xvf velero-v1.14.0-linux-amd64.tar.gz
sudo mv velero-v1.14.0-linux-amd64/velero /usr/local/bin/
```

### Step 3.2: Create Velero Credentials Secret

```bash
# Create credentials file
cat > /tmp/minio-credentials <<EOF
[default]
aws_access_key_id=<YOUR_MINIO_ACCESS_KEY>
aws_secret_access_key=<YOUR_MINIO_SECRET_KEY>
EOF

# Create namespace
kubectl create namespace velero

# Create secret
kubectl create secret generic velero-minio-credentials \
  -n velero \
  --from-file=cloud=/tmp/minio-credentials

# Clean up credentials file
rm /tmp/minio-credentials
```

### Step 3.3: Install Velero

```bash
velero install \
  --provider aws \
  --plugins velero/velero-plugin-for-aws:v1.10.0 \
  --bucket velero-backups \
  --secret-file /tmp/minio-credentials \
  --backup-location-config region=minio,s3ForcePathStyle="true",s3Url=http://192.168.1.230:9000 \
  --use-node-agent \
  --default-volumes-to-fs-backup

# Or apply via ArgoCD (after ArgoCD is restored)
kubectl apply -f /path/to/k8s/velero-app.yaml
```

### Step 3.4: Verify Velero Installation

```bash
# Check Velero pods
kubectl get pods -n velero

# Verify backup location is available
velero backup-location get

# List available backups from MinIO
velero backup get
```

## Phase 4: Restore Applications from Backup

### Step 4.1: Identify Latest Valid Backup

```bash
# List all backups
velero backup get

# Get details of latest backup
velero backup describe <latest-backup-name> --details

# Verify backup completed successfully
velero backup logs <latest-backup-name> | grep -i error
```

### Step 4.2: Full Cluster Restore

```bash
# Restore all namespaces from backup
velero restore create full-restore-$(date +%Y%m%d) \
  --from-backup <backup-name> \
  --include-namespaces media,pihole,nginx-proxy-manager,home-apps,default

# Monitor restore progress
velero restore describe full-restore-$(date +%Y%m%d) --details

# Check restore logs
velero restore logs full-restore-$(date +%Y%m%d)
```

### Step 4.3: Restore Specific Namespaces (Alternative)

```bash
# Restore namespaces one at a time for more control
for ns in pihole nginx-proxy-manager media home-apps default; do
  velero restore create restore-${ns}-$(date +%Y%m%d) \
    --from-backup <backup-name> \
    --include-namespaces $ns

  echo "Waiting for $ns restore to complete..."
  velero restore wait restore-${ns}-$(date +%Y%m%d)
done
```

### Step 4.4: Verify Restored Resources

```bash
# Check all namespaces
kubectl get pods -A

# Check PVCs are bound
kubectl get pvc -A

# Check services
kubectl get svc -A

# Check specific applications
kubectl get pods -n media
kubectl get pods -n pihole
kubectl get pods -n nginx-proxy-manager
```

## Phase 5: Post-Recovery Validation

### Step 5.1: Verify Application Health

```bash
# Check Pi-hole
kubectl logs -n pihole -l app=pihole --tail=20

# Check Sonarr
kubectl logs -n media -l app.kubernetes.io/name=sonarr --tail=20

# Check Radarr
kubectl logs -n media -l app.kubernetes.io/name=radarr --tail=20

# Check nginx-proxy-manager
kubectl logs -n nginx-proxy-manager -l app.kubernetes.io/name=nginx-proxy-manager --tail=20
```

### Step 5.2: Verify Data Integrity

1. **Pi-hole:**
   - Access web UI (http://192.168.10.53/admin)
   - Verify blocklists are configured
   - Test DNS resolution

2. **Sonarr/Radarr:**
   - Access web UIs
   - Verify series/movies are listed
   - Check download clients are connected

3. **nginx-proxy-manager:**
   - Access admin UI
   - Verify proxy hosts are configured
   - Check SSL certificates

### Step 5.3: Restore ArgoCD Applications

```bash
# Apply all ArgoCD application manifests
kubectl apply -f /path/to/k8s/*-app.yaml

# Force sync all applications
argocd app sync --all

# Or via ArgoCD UI:
# 1. Login to ArgoCD
# 2. Sync all applications
```

### Step 5.4: Re-create Manual Secrets

Some secrets are not stored in git and must be recreated:

```bash
# Pi-hole secret
kubectl create secret generic pihole-secret -n pihole \
  --from-literal=WEBPASSWORD=<password>

# Other application secrets as needed
# Check each app's documentation for required secrets
```

## Recovery Time Objectives

| Phase | Estimated Time | Notes |
|-------|---------------|-------|
| k3s installation | 5-10 minutes | Single node |
| ArgoCD installation | 5 minutes | |
| democratic-csi | 5 minutes | |
| Velero installation | 5 minutes | |
| Full restore | 15-30 minutes | Depends on data size |
| Validation | 15-30 minutes | |
| **Total** | **45-90 minutes** | |

## Troubleshooting

### Velero Cannot Connect to MinIO

```bash
# Verify MinIO is accessible
curl -v http://192.168.1.230:9000/minio/health/live

# Check Velero logs
kubectl logs -n velero deployment/velero

# Verify credentials
kubectl get secret velero-minio-credentials -n velero -o yaml
```

### PVCs Not Binding After Restore

```bash
# Check PV status
kubectl get pv

# Check storage class exists
kubectl get storageclass

# Check democratic-csi is running
kubectl get pods -n democratic-csi

# Check iSCSI connectivity to TrueNAS
kubectl logs -n democratic-csi -l app.kubernetes.io/name=democratic-csi
```

### Pods Failing to Start

```bash
# Describe pod for events
kubectl describe pod <pod-name> -n <namespace>

# Check PVC is bound
kubectl get pvc -n <namespace>

# Check node agent pods
kubectl get pods -n velero -l name=node-agent
```

## Related Documentation

- [Single App Restore](./restore-single-app.md) - For targeted recovery
- [ZFS Snapshot Guide](./zfs-snapshot-guide.md) - Alternative recovery path
- [etcd Backup Guide](./etcd-backup-guide.md) - k3s cluster state backup
- [Troubleshooting Guide](./troubleshooting.md) - Common issues
