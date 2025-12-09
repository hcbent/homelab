# Velero Troubleshooting Guide

This guide covers common issues and solutions when using Velero for Kubernetes backup and recovery.

## Quick Diagnostic Commands

```bash
# Check Velero components
kubectl get pods -n velero
kubectl get backupstoragelocations -n velero
kubectl get schedules -n velero

# Check Velero server logs
kubectl logs -n velero deployment/velero

# Check node-agent (Restic/Kopia) logs
kubectl logs -n velero -l name=node-agent -c node-agent

# Describe specific backup
velero backup describe <backup-name> --details

# Check backup logs
velero backup logs <backup-name>
```

## Common Issues

### 1. BackupStorageLocation Shows "Unavailable"

**Symptoms:**
```bash
$ velero backup-location get
NAME      PROVIDER   BUCKET/PREFIX     PHASE         LAST VALIDATED
default   aws        velero-backups    Unavailable   30s ago
```

**Causes and Solutions:**

**A. MinIO Connection Failed**

```bash
# Test MinIO connectivity
curl -v http://192.168.1.230:9000/minio/health/live

# Check MinIO is running on Synology
# - Access Synology DSM
# - Check Docker/Container Manager for MinIO container
```

**B. Invalid Credentials**

```bash
# Verify secret exists
kubectl get secret velero-minio-credentials -n velero

# Check secret contents
kubectl get secret velero-minio-credentials -n velero -o yaml | grep cloud

# Recreate secret with correct credentials
kubectl delete secret velero-minio-credentials -n velero
kubectl create secret generic velero-minio-credentials -n velero \
  --from-literal=cloud="$(cat <<EOF
[default]
aws_access_key_id=<CORRECT_ACCESS_KEY>
aws_secret_access_key=<CORRECT_SECRET_KEY>
EOF
)"
```

**C. Bucket Does Not Exist**

```bash
# Check bucket exists on MinIO
# Use MinIO Console or mc CLI:
mc ls minio/velero-backups

# Create bucket if missing
mc mb minio/velero-backups
```

**D. Wrong S3 Configuration**

```bash
# Verify BackupStorageLocation config
kubectl get backupstoragelocation default -n velero -o yaml

# Ensure these settings are correct:
# - s3Url: http://192.168.1.230:9000
# - region: minio
# - s3ForcePathStyle: "true"
```

---

### 2. Backup Stuck in "InProgress" State

**Symptoms:**
```bash
$ velero backup get
NAME                    STATUS       CREATED                         EXPIRES
daily-backup-20240115   InProgress   2024-01-15 02:00:00 +0000 UTC   6d
```

**Causes and Solutions:**

**A. Node-agent (Restic) Pod Issues**

```bash
# Check node-agent pods are running on all nodes
kubectl get pods -n velero -l name=node-agent -o wide

# Check node-agent logs
kubectl logs -n velero -l name=node-agent -c node-agent --tail=50

# Common fix: Restart node-agent
kubectl rollout restart daemonset/node-agent -n velero
```

**B. Large Volume Taking Time**

```bash
# Check PodVolumeBackup status
kubectl get podvolumebackups -n velero | grep <backup-name>

# Monitor progress
kubectl describe podvolumebackup <pvb-name> -n velero
```

**C. Volume Not Accessible**

```bash
# Check if PVC is bound
kubectl get pvc -A

# Ensure pod using volume is running
kubectl get pods -A -o wide | grep <app-name>

# Check iSCSI connectivity (for democratic-csi volumes)
kubectl logs -n democratic-csi -l app.kubernetes.io/name=democratic-csi
```

**D. Stuck Backup - Force Deletion**

```bash
# If backup is truly stuck, delete it
velero backup delete <backup-name>

# If delete hangs, patch finalizers
kubectl patch backup <backup-name> -n velero -p '{"metadata":{"finalizers":null}}' --type=merge
kubectl delete backup <backup-name> -n velero
```

---

### 3. PVC Data Not Being Backed Up

**Symptoms:**
- Backup completes but PVC restore shows empty data
- PodVolumeBackup resources not created

**Causes and Solutions:**

**A. defaultVolumesToFsBackup Not Enabled**

```bash
# Check backup/schedule configuration
velero backup describe <backup-name> | grep "Default volumes"

# Update schedule to include fs backup
# In velero/schedules/daily-backup.yaml:
# spec:
#   template:
#     defaultVolumesToFsBackup: true
```

**B. Node-Agent Not Running on Node**

```bash
# Check which nodes have node-agent
kubectl get pods -n velero -l name=node-agent -o wide

# If missing on a node, check tolerations/nodeSelector
kubectl describe daemonset node-agent -n velero
```

**C. Volume Type Not Supported**

```bash
# Verify PVC is using supported volume type
kubectl get pvc <pvc-name> -n <namespace> -o yaml | grep storageClassName

# For hostPath volumes, annotate pod:
# backup.velero.io/backup-volumes: <volume-name>
```

**D. Pod Not Running During Backup**

```bash
# Velero can only backup volumes from running pods
kubectl get pods -n <namespace>

# Ensure application pods are running at backup time
```

---

### 4. Restore Fails with Errors

**Symptoms:**
```bash
$ velero restore describe <restore-name>
Phase: PartiallyFailed
Errors: 5
```

**Causes and Solutions:**

**A. Resource Already Exists**

```bash
# Check restore logs for conflicts
velero restore logs <restore-name> | grep -i "already exists"

# Options:
# 1. Delete existing resource before restore
# 2. Use --existing-resource-policy=update

velero restore create <name> \
  --from-backup <backup> \
  --existing-resource-policy=update
```

**B. Namespace Mismatch**

```bash
# Check namespace exists
kubectl get namespace <target-namespace>

# Create if missing
kubectl create namespace <target-namespace>

# Or use namespace mapping
velero restore create <name> \
  --from-backup <backup> \
  --namespace-mappings old-ns:new-ns
```

**C. Storage Class Not Found**

```bash
# Check storage classes exist
kubectl get storageclass

# If using different storage class, use mapping
velero restore create <name> \
  --from-backup <backup> \
  --restore-volumes=true
```

**D. Webhook Rejection**

```bash
# Check for admission webhook errors
velero restore logs <restore-name> | grep -i webhook

# Temporarily disable webhooks if needed
# Or restore without specific resources
velero restore create <name> \
  --from-backup <backup> \
  --exclude-resources mutatingwebhookconfigurations,validatingwebhookconfigurations
```

---

### 5. Schedule Not Creating Backups

**Symptoms:**
```bash
$ velero schedule get
NAME             STATUS    CREATED                         SCHEDULE      BACKUP TTL
daily-backup     Enabled   2024-01-01 00:00:00 +0000 UTC   0 2 * * *     168h0m0s

$ velero backup get
NAME   STATUS   CREATED   EXPIRES
# No backups from schedule
```

**Causes and Solutions:**

**A. Schedule Paused**

```bash
# Check schedule status
velero schedule get

# Unpause if paused
velero schedule unpause <schedule-name>
```

**B. Invalid Cron Expression**

```bash
# Verify cron expression in schedule
kubectl get schedule <schedule-name> -n velero -o yaml | grep schedule

# Test cron expression at crontab.guru
```

**C. Velero Server Not Running**

```bash
# Check Velero deployment
kubectl get deployment velero -n velero

# Restart if needed
kubectl rollout restart deployment/velero -n velero
```

**D. Time Zone Issues**

```bash
# Velero uses UTC by default
# Verify schedule time is correct for UTC

# Current UTC time
date -u
```

---

### 6. Slow Backup Performance

**Symptoms:**
- Backups take hours to complete
- High CPU/memory on nodes during backup

**Causes and Solutions:**

**A. Large Volume Data**

```bash
# Check volume sizes
kubectl get pvc -A -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,SIZE:.spec.resources.requests.storage'

# Consider excluding large media volumes
# In schedule spec:
# excludedResources:
#   - persistentvolumeclaims/video-pvc
```

**B. Network Bandwidth**

```bash
# Check MinIO upload speed
# Test with a small manual backup

# Consider running backups during off-hours
```

**C. Node-Agent Resource Limits**

```bash
# Check node-agent resource usage
kubectl top pods -n velero -l name=node-agent

# Increase resources in velero-values.yaml:
# nodeAgent:
#   resources:
#     limits:
#       cpu: 2000m
#       memory: 2Gi
```

---

### 7. Credentials Issues

**Symptoms:**
- Access Denied errors in logs
- Signature mismatch errors

**Solutions:**

```bash
# Verify secret format
kubectl get secret velero-minio-credentials -n velero -o jsonpath='{.data.cloud}' | base64 -d

# Should output:
# [default]
# aws_access_key_id=<key>
# aws_secret_access_key=<secret>

# Recreate with correct format
kubectl delete secret velero-minio-credentials -n velero
kubectl create secret generic velero-minio-credentials -n velero \
  --from-file=cloud=/path/to/credentials-file
```

---

## Debug Mode

Enable debug logging for more verbose output:

```bash
# Patch Velero deployment for debug logging
kubectl set env deployment/velero -n velero VELERO_DEBUG=true

# Or in velero-values.yaml:
# configuration:
#   logLevel: debug
```

## Health Checks

### Regular Health Check Commands

```bash
#!/bin/bash
# velero-health-check.sh

echo "=== Velero Pods ==="
kubectl get pods -n velero

echo "=== Backup Storage Location ==="
velero backup-location get

echo "=== Recent Backups ==="
velero backup get | head -10

echo "=== Schedules ==="
velero schedule get

echo "=== Recent Errors ==="
kubectl logs -n velero deployment/velero --since=1h | grep -i error | tail -20
```

### Monitoring Alerts (if using Prometheus)

```yaml
# Example PrometheusRule for Velero monitoring
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: velero-alerts
  namespace: velero
spec:
  groups:
  - name: velero
    rules:
    - alert: VeleroBackupFailed
      expr: velero_backup_failure_total > 0
      for: 1h
      labels:
        severity: warning
      annotations:
        summary: "Velero backup failed"
```

## Related Documentation

- [Single App Restore](./restore-single-app.md)
- [Disaster Recovery Runbook](./disaster-recovery-runbook.md)
- [ZFS Snapshot Guide](./zfs-snapshot-guide.md)
- [Velero Documentation](https://velero.io/docs/)
