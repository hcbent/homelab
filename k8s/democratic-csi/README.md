# Democratic CSI Storage Configuration

This directory contains the configuration for Democratic CSI storage drivers that integrate with FreeNAS/TrueNAS for persistent volume provisioning in the Kubernetes cluster.

## Overview

Democratic CSI provides two storage backends:
- **iSCSI**: Block storage for high-performance workloads (default storage class)
- **NFS**: Shared storage for ReadWriteMany volumes

## Prerequisites

### On Worker Nodes

Before deploying Democratic CSI, ensure iSCSI initiator is installed on all worker nodes:

```bash
# SSH to each worker node (kube01, kube02, kube03)
sudo apt-get update
sudo apt-get install -y open-iscsi
sudo systemctl enable --now iscsid
sudo systemctl status iscsid
```

### On FreeNAS/TrueNAS

1. **API Access**: Generate API key in TrueNAS web UI
2. **SSH Access**: Configure SSH key authentication for root user
3. **Storage Pools**: Ensure the following datasets exist:
   - `tank/k8s/volumes` - iSCSI volumes
   - `tank/k8s/snapshots` - iSCSI snapshots
   - `tank/k8s/nfs` - NFS volumes
   - `tank/k8s/nfs-snapshots` - NFS snapshots

4. **iSCSI Configuration**:
   - Target Portal configured
   - Initiator Group configured (allow all or specific initiators)
   - Portal Group configured

### Credentials in Vault

Store FreeNAS credentials in Vault at `secret/homelab/freenas/credentials`:

```bash
vault kv put secret/homelab/freenas/credentials \
  api_key="your-api-key-here" \
  root_password="your-root-password-here" \
  ssh_private_key="$(cat ~/.ssh/freenas_rsa)"
```

## Configuration Files

### `namespace.yaml`
Creates the `democratic-csi` namespace for all CSI components.

### `values-iscsi.yaml`
Helm values for the iSCSI driver. Before deploying, update:
- `<FREENAS_IP>`: Replace with your FreeNAS/TrueNAS IP address
- `<RETRIEVE_FROM_VAULT>`: Retrieve and inject credentials from Vault

### `values-nfs.yaml`
Helm values for the NFS driver. Before deploying, update:
- `<FREENAS_IP>`: Replace with your FreeNAS/TrueNAS IP address
- `<RETRIEVE_FROM_VAULT>`: Retrieve and inject credentials from Vault

## Deployment

### Manual Deployment

1. **Create Namespace**:
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/democratic-csi/namespace.yaml
```

2. **Retrieve Credentials from Vault**:
```bash
# Set your Vault token
export VAULT_ADDR=https://192.168.10.101:8200
export VAULT_TOKEN=<your-token>

# Retrieve credentials
vault kv get secret/homelab/freenas/credentials
```

3. **Update Values Files**:
Edit `values-iscsi.yaml` and `values-nfs.yaml` to replace placeholders with actual values:
- Replace `<FREENAS_IP>` with your FreeNAS IP
- Replace `<RETRIEVE_FROM_VAULT>` with credentials from Vault

4. **Add Helm Repository**:
```bash
helm repo add democratic-csi https://democratic-csi.github.io/charts/
helm repo update
```

5. **Deploy iSCSI Driver**:
```bash
helm install democratic-csi-iscsi democratic-csi/democratic-csi \
  -n democratic-csi \
  -f /Users/bret/git/homelab/k8s/democratic-csi/values-iscsi.yaml
```

6. **Deploy NFS Driver**:
```bash
helm install democratic-csi-nfs democratic-csi/democratic-csi \
  -n democratic-csi \
  -f /Users/bret/git/homelab/k8s/democratic-csi/values-nfs.yaml
```

### Deployment via ArgoCD

Create ArgoCD Application manifests for both drivers (recommended for GitOps):

```yaml
# democratic-csi-iscsi-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: democratic-csi-iscsi
  namespace: argocd
spec:
  project: default
  destination:
    namespace: democratic-csi
    server: https://kubernetes.default.svc
  sources:
    - repoURL: https://democratic-csi.github.io/charts/
      targetRevision: 0.14.6
      chart: democratic-csi
      helm:
        valueFiles:
          - $values/k8s/democratic-csi/values-iscsi.yaml
    - repoURL: git@github.com/wortmanb/homelab.git
      path: k8s/democratic-csi
      targetRevision: main
      ref: values
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
    automated: {}
```

## Verification

### Check Deployment Status

```bash
# Check democratic-csi pods
kubectl get pods -n democratic-csi

# Expected output:
# NAME                                            READY   STATUS    RESTARTS   AGE
# freenas-iscsi-controller-xxxxx                  6/6     Running   0          5m
# freenas-iscsi-node-xxxxx                        4/4     Running   0          5m
# freenas-nfs-controller-xxxxx                    5/5     Running   0          5m
# freenas-nfs-node-xxxxx                          3/3     Running   0          5m
```

### Check Storage Classes

```bash
kubectl get storageclass

# Expected output:
# NAME                        PROVISIONER                   RECLAIMPOLICY   VOLUMEBINDINGMODE   ALLOWVOLUMEEXPANSION
# freenas-iscsi-csi (default) org.democratic-csi.iscsi     Delete          Immediate           true
# freenas-nfs-csi             org.democratic-csi.nfs        Delete          Immediate           true
```

### Test Volume Provisioning

Create a test PVC to verify iSCSI storage:

```bash
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc-iscsi
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: freenas-iscsi-csi
EOF

# Check PVC status
kubectl get pvc test-pvc-iscsi

# Expected: STATUS should be "Bound"

# Clean up test PVC
kubectl delete pvc test-pvc-iscsi
```

Test NFS storage:

```bash
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc-nfs
  namespace: default
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 1Gi
  storageClassName: freenas-nfs-csi
EOF

# Check PVC status
kubectl get pvc test-pvc-nfs

# Clean up
kubectl delete pvc test-pvc-nfs
```

## Troubleshooting

### Pods in CrashLoopBackOff

Check logs:
```bash
kubectl logs -n democratic-csi <pod-name> -c csi-driver
```

Common issues:
- FreeNAS API credentials incorrect
- SSH key authentication failed
- FreeNAS datasets don't exist
- Network connectivity issues to FreeNAS

### PVC Stuck in Pending

```bash
# Describe PVC to see events
kubectl describe pvc <pvc-name>

# Check CSI controller logs
kubectl logs -n democratic-csi <controller-pod-name> -c csi-driver
```

Common issues:
- Storage class not found or misconfigured
- Insufficient space on FreeNAS pool
- iSCSI initiator not installed on worker nodes
- FreeNAS portal/initiator group misconfiguration

### iSCSI Connection Issues

On worker nodes:
```bash
# Check iSCSI service
sudo systemctl status iscsid

# Check discovered targets
sudo iscsiadm -m discovery -t st -p <FREENAS_IP>:3260

# Check iSCSI sessions
sudo iscsiadm -m session
```

### Volume Mount Failures

Check node logs:
```bash
kubectl logs -n democratic-csi <node-pod-name> -c csi-driver
```

Common issues:
- Filesystem type mismatch
- Mount options incompatible
- Node doesn't have required filesystem utilities (ext4, xfs tools)

## Storage Class Usage

### For Single-Node Applications (RWO)

Use `freenas-iscsi-csi` (default):
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-app-data
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  # storageClassName can be omitted since freenas-iscsi-csi is default
```

### For Multi-Node Applications (RWX)

Use `freenas-nfs-csi`:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: shared-data
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 50Gi
  storageClassName: freenas-nfs-csi
```

## Volume Snapshots

Both drivers support volume snapshots:

```bash
# List snapshot classes
kubectl get volumesnapshotclass

# Create a snapshot
cat <<EOF | kubectl apply -f -
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: my-snapshot
  namespace: default
spec:
  volumeSnapshotClassName: freenas-iscsi-snapshots
  source:
    persistentVolumeClaimName: my-pvc
EOF

# Check snapshot status
kubectl get volumesnapshot my-snapshot

# Restore from snapshot
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: restored-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: freenas-iscsi-csi
  dataSource:
    name: my-snapshot
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
EOF
```

## Maintenance

### Upgrading Democratic CSI

```bash
# Update Helm repo
helm repo update

# Upgrade iSCSI driver
helm upgrade democratic-csi-iscsi democratic-csi/democratic-csi \
  -n democratic-csi \
  -f /Users/bret/git/homelab/k8s/democratic-csi/values-iscsi.yaml

# Upgrade NFS driver
helm upgrade democratic-csi-nfs democratic-csi/democratic-csi \
  -n democratic-csi \
  -f /Users/bret/git/homelab/k8s/democratic-csi/values-nfs.yaml
```

### Uninstalling

```bash
# WARNING: Ensure no volumes are in use before uninstalling

# Delete Helm releases
helm uninstall democratic-csi-iscsi -n democratic-csi
helm uninstall democratic-csi-nfs -n democratic-csi

# Delete namespace
kubectl delete namespace democratic-csi
```

## References

- [Democratic CSI GitHub](https://github.com/democratic-csi/democratic-csi)
- [Democratic CSI Helm Chart](https://github.com/democratic-csi/charts)
- [TrueNAS API Documentation](https://www.truenas.com/docs/api/)
- [Kubernetes CSI Documentation](https://kubernetes-csi.github.io/docs/)
