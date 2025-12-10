# Restoring a Single Application from Velero Backup

This guide covers the procedure for restoring a single application or namespace from a Velero backup without affecting other services.

## Prerequisites

- Velero CLI installed: `brew install velero` (macOS) or download from GitHub releases
- kubectl access to the cluster
- Knowledge of which backup contains the data you need

## Pre-Restore Checklist

Before initiating a restore, complete these steps:

- [ ] Identify the target backup
- [ ] Verify backup integrity
- [ ] Scale down or delete the target application
- [ ] Ensure PVC is not in use
- [ ] Document current state (for rollback if needed)

## Step 1: Identify and Verify the Backup

### List Available Backups

```bash
# List all backups
velero backup get

# List backups with details
velero backup get -o wide

# Filter by schedule
velero backup get --selector velero.io/schedule-name=daily-backup
```

### Verify Backup Contents

```bash
# Describe a specific backup
velero backup describe <backup-name> --details

# Check backup logs for errors
velero backup logs <backup-name>

# List resources in the backup
velero backup describe <backup-name> --details | grep -A 50 "Resource List"
```

### Example: Finding Sonarr Backup

```bash
# Find latest daily backup
velero backup get --selector velero.io/schedule-name=daily-backup -o name | head -1

# Verify it contains media namespace resources
velero backup describe daily-backup-20240115020000 --details | grep -E "media|sonarr"
```

## Step 2: Prepare the Target Application

### Option A: Scale Down (Recommended for Updates)

```bash
# Scale down the deployment
kubectl scale deployment <app-name> -n <namespace> --replicas=0

# Verify pods are terminated
kubectl get pods -n <namespace> -l app.kubernetes.io/name=<app-name>

# Wait for termination
kubectl wait --for=delete pod -l app.kubernetes.io/name=<app-name> -n <namespace> --timeout=60s
```

### Option B: Delete Existing Resources (Clean Restore)

```bash
# Delete the deployment (PVC will remain due to protection)
kubectl delete deployment <app-name> -n <namespace>

# Optionally delete the PVC (WARNING: Data loss!)
# Only if you want to restore PVC data from backup
# kubectl delete pvc <pvc-name> -n <namespace>
```

## Step 3: Perform the Restore

### Restore Entire Namespace

```bash
velero restore create <restore-name> \
  --from-backup <backup-name> \
  --include-namespaces <namespace>

# Example: Restore media namespace
velero restore create restore-media-20240115 \
  --from-backup daily-backup-20240115020000 \
  --include-namespaces media
```

### Restore Specific Resources Only

```bash
# Restore only PVCs and their data
velero restore create restore-sonarr-pvc \
  --from-backup daily-backup-20240115020000 \
  --include-namespaces media \
  --include-resources persistentvolumeclaims,persistentvolumes

# Restore only ConfigMaps and Secrets
velero restore create restore-config \
  --from-backup daily-backup-20240115020000 \
  --include-namespaces media \
  --include-resources configmaps,secrets
```

### Restore with Label Selector

```bash
# Restore only resources with specific label
velero restore create restore-sonarr \
  --from-backup daily-backup-20240115020000 \
  --include-namespaces media \
  --selector app.kubernetes.io/name=sonarr
```

### Restore to a Different Namespace (Testing)

```bash
# Restore pihole to a test namespace for verification
velero restore create test-restore-pihole \
  --from-backup daily-backup-20240115020000 \
  --include-namespaces pihole \
  --namespace-mappings pihole:pihole-restore-test
```

## Step 4: Monitor the Restore

### Check Restore Status

```bash
# Watch restore progress
velero restore describe <restore-name> --details

# Check for warnings/errors
velero restore logs <restore-name>

# List all restores
velero restore get
```

### Verify Restored Resources

```bash
# Check PVCs are restored
kubectl get pvc -n <namespace>

# Check PVC is bound
kubectl get pvc -n <namespace> -o wide

# Check deployments
kubectl get deployments -n <namespace>

# Check pods are running
kubectl get pods -n <namespace>
```

## Step 5: Post-Restore Validation

### Scale Up Application (if scaled down)

```bash
kubectl scale deployment <app-name> -n <namespace> --replicas=1
```

### Verify Application Health

```bash
# Check pod status
kubectl get pods -n <namespace> -l app.kubernetes.io/name=<app-name>

# Check pod logs
kubectl logs -n <namespace> -l app.kubernetes.io/name=<app-name>

# Check application endpoint (if service exists)
kubectl get svc -n <namespace>
```

### Verify Data Integrity

1. Access the application UI
2. Check that expected data is present
3. Verify application functionality

## Common Restore Scenarios

### Scenario 1: Restore After Accidental PVC Deletion

```bash
# 1. PVC was deleted, application is failing
kubectl get pvc -n media
# Shows: sonarr-config PVC missing

# 2. Find backup with the PVC
velero backup describe daily-backup-20240115020000 --details | grep sonarr

# 3. Delete the failing deployment
kubectl delete deployment sonarr -n media

# 4. Restore from backup
velero restore create restore-sonarr-$(date +%Y%m%d) \
  --from-backup daily-backup-20240115020000 \
  --include-namespaces media \
  --selector app.kubernetes.io/name=sonarr

# 5. Verify restoration
kubectl get pvc,deployment,pods -n media -l app.kubernetes.io/name=sonarr
```

### Scenario 2: Restore Configuration Only (Keep Existing PVC Data)

```bash
# 1. Scale down
kubectl scale deployment pihole -n pihole --replicas=0

# 2. Restore only configmaps and secrets
velero restore create restore-pihole-config \
  --from-backup daily-backup-20240115020000 \
  --include-namespaces pihole \
  --include-resources configmaps,secrets

# 3. Scale back up
kubectl scale deployment pihole -n pihole --replicas=1
```

### Scenario 3: Test Restore to Verify Backup Integrity

```bash
# 1. Create test namespace
kubectl create namespace restore-test

# 2. Restore to test namespace
velero restore create test-pihole \
  --from-backup daily-backup-20240115020000 \
  --include-namespaces pihole \
  --namespace-mappings pihole:restore-test

# 3. Verify data in test namespace
kubectl get all -n restore-test
kubectl exec -n restore-test <pod-name> -- ls /config

# 4. Clean up test namespace
kubectl delete namespace restore-test
```

## Troubleshooting

### Restore Stuck in "InProgress"

```bash
# Check Velero server logs
kubectl logs -n velero -l name=velero

# Check node-agent (Restic) logs
kubectl logs -n velero -l name=node-agent -c node-agent
```

### PVC Already Exists Error

If restoring fails because PVC already exists:

```bash
# Option 1: Exclude PVC from restore (keep existing data)
velero restore create <restore-name> \
  --from-backup <backup-name> \
  --exclude-resources persistentvolumeclaims

# Option 2: Delete existing PVC first (WARNING: Data loss)
kubectl delete pvc <pvc-name> -n <namespace>
```

### Restore Completes But Data Missing

```bash
# Check if Restic/file-system backup was used
velero backup describe <backup-name> --details | grep -i restic

# Verify PodVolumeBackup resources exist
kubectl get podvolumebackups -n velero | grep <backup-name>
```

### Namespace Mapping Issues

```bash
# Ensure target namespace exists
kubectl create namespace <target-namespace>

# Check for namespace-specific resources (like NetworkPolicies)
velero restore describe <restore-name> --details | grep -i warning
```

## Related Documentation

- [Disaster Recovery Runbook](./disaster-recovery-runbook.md) - Full cluster restore
- [ZFS Snapshot Guide](./zfs-snapshot-guide.md) - Alternative fast local recovery
- [Troubleshooting Guide](./troubleshooting.md) - Common issues and solutions
