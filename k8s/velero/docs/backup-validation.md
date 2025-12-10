# Backup Validation Guide

This guide documents procedures for validating Velero backups and ensuring data recoverability.

## Purpose

Regular backup validation ensures:
- Backups are completing successfully
- Data can be restored when needed
- Recovery procedures work as documented
- Backup retention policies are functioning

## Validation Frequency

| Validation Type | Frequency | Estimated Time |
|-----------------|-----------|----------------|
| Backup status check | Daily (automated) | 5 minutes |
| Backup content review | Weekly | 15 minutes |
| Test restore to staging | Monthly | 30-60 minutes |
| Full DR test | Quarterly | 2-4 hours |

## Daily Backup Status Check

### Automated Check Script

```bash
#!/bin/bash
# backup-status-check.sh
# Run via cron or monitoring system

set -e

echo "=== Velero Backup Status Check - $(date) ==="

# Check BackupStorageLocation is available
BSL_STATUS=$(velero backup-location get -o json | jq -r '.items[0].status.phase')
if [ "$BSL_STATUS" != "Available" ]; then
  echo "ERROR: BackupStorageLocation is $BSL_STATUS"
  exit 1
fi
echo "BackupStorageLocation: Available"

# Check latest daily backup completed
LATEST_DAILY=$(velero backup get -l velero.io/schedule-name=daily-backup -o json | \
  jq -r '.items | sort_by(.metadata.creationTimestamp) | last | .status.phase')
if [ "$LATEST_DAILY" != "Completed" ]; then
  echo "ERROR: Latest daily backup status: $LATEST_DAILY"
  exit 1
fi
echo "Latest daily backup: Completed"

# Check backup age (should be less than 25 hours old)
LATEST_BACKUP_TIME=$(velero backup get -l velero.io/schedule-name=daily-backup -o json | \
  jq -r '.items | sort_by(.metadata.creationTimestamp) | last | .metadata.creationTimestamp')
BACKUP_AGE_HOURS=$(( ($(date +%s) - $(date -d "$LATEST_BACKUP_TIME" +%s)) / 3600 ))
if [ "$BACKUP_AGE_HOURS" -gt 25 ]; then
  echo "ERROR: Latest backup is $BACKUP_AGE_HOURS hours old"
  exit 1
fi
echo "Backup age: ${BACKUP_AGE_HOURS} hours (OK)"

# Check node-agent pods
NODE_AGENT_READY=$(kubectl get pods -n velero -l name=node-agent -o json | \
  jq '[.items[].status.containerStatuses[].ready] | all')
if [ "$NODE_AGENT_READY" != "true" ]; then
  echo "ERROR: Not all node-agent pods are ready"
  exit 1
fi
echo "Node-agent pods: Ready"

echo "=== All checks passed ==="
```

### Manual Daily Check

```bash
# Quick health check
velero backup-location get
velero backup get | head -5
velero schedule get
kubectl get pods -n velero
```

## Weekly Backup Content Review

### Step 1: Review Backup Details

```bash
# Get latest daily backup name
BACKUP_NAME=$(velero backup get -l velero.io/schedule-name=daily-backup -o name | tail -1)

# View backup details
velero backup describe $BACKUP_NAME --details
```

### Step 2: Verify Namespaces Included

```bash
# Check namespaces in backup
velero backup describe $BACKUP_NAME | grep -A 20 "Namespaces:"

# Expected namespaces:
# - media
# - pihole
# - nginx-proxy-manager
# - home-apps
# - default
```

### Step 3: Verify PVC Backups

```bash
# List PodVolumeBackups
kubectl get podvolumebackups -n velero | grep $BACKUP_NAME

# Check each PVC was backed up
velero backup describe $BACKUP_NAME --details | grep -A 50 "Restic Backups"
```

### Step 4: Check Backup Size

```bash
# Via MinIO Console or mc CLI
mc du minio/velero-backups/backups/$BACKUP_NAME
```

### Weekly Review Checklist

- [ ] All schedules are enabled
- [ ] Latest daily backup completed successfully
- [ ] Latest weekly backup completed successfully
- [ ] All expected namespaces are included
- [ ] PVC data was captured (PodVolumeBackups exist)
- [ ] Backup size is reasonable (not suspiciously small)
- [ ] No error messages in backup logs

## Monthly Test Restore

### Preparation

1. Create a test namespace
2. Restore a single application
3. Verify data integrity
4. Clean up

### Step 1: Create Test Namespace

```bash
kubectl create namespace restore-test
```

### Step 2: Perform Test Restore

```bash
# Get latest backup
BACKUP_NAME=$(velero backup get -l velero.io/schedule-name=daily-backup -o name | tail -1 | cut -d'/' -f2)

# Restore pihole to test namespace
velero restore create test-restore-$(date +%Y%m%d) \
  --from-backup $BACKUP_NAME \
  --include-namespaces pihole \
  --namespace-mappings pihole:restore-test

# Monitor restore
velero restore describe test-restore-$(date +%Y%m%d) --details
```

### Step 3: Verify Restored Resources

```bash
# Check all resources restored
kubectl get all -n restore-test

# Check PVCs are bound
kubectl get pvc -n restore-test

# Check ConfigMaps and Secrets
kubectl get configmaps,secrets -n restore-test
```

### Step 4: Verify Data Integrity

```bash
# If pod is running, check data exists
kubectl exec -n restore-test <pod-name> -- ls -la /etc/pihole/

# For other apps, verify config files exist
kubectl exec -n restore-test <pod-name> -- cat /config/config.xml 2>/dev/null || echo "Config check complete"
```

### Step 5: Clean Up

```bash
# Delete test namespace and all resources
kubectl delete namespace restore-test

# Delete the restore record
velero restore delete test-restore-$(date +%Y%m%d)
```

### Monthly Test Checklist

- [ ] Test namespace created successfully
- [ ] Restore completed without errors
- [ ] All expected resources were restored
- [ ] PVCs are bound and contain data
- [ ] ConfigMaps and Secrets restored
- [ ] Data integrity verified
- [ ] Test namespace cleaned up
- [ ] Document any issues found

## Quarterly DR Test

### Full Disaster Recovery Simulation

This test validates the complete disaster recovery process.

**Note:** This is a more intensive test. Schedule during maintenance window.

### Step 1: Document Current State

```bash
# Export current resource counts
kubectl get all -A -o wide > /tmp/pre-dr-state.txt
kubectl get pvc -A -o wide >> /tmp/pre-dr-state.txt
```

### Step 2: Perform Multi-Namespace Restore

```bash
# Create test namespaces
for ns in media-test pihole-test npm-test; do
  kubectl create namespace $ns
done

# Restore multiple namespaces
velero restore create dr-test-$(date +%Y%m%d) \
  --from-backup $BACKUP_NAME \
  --include-namespaces media,pihole,nginx-proxy-manager \
  --namespace-mappings media:media-test,pihole:pihole-test,nginx-proxy-manager:npm-test
```

### Step 3: Validate Each Application

```bash
# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=sonarr -n media-test --timeout=300s
kubectl wait --for=condition=ready pod -l app=pihole -n pihole-test --timeout=300s
```

### Step 4: Document Results

Record the following:
- Time to complete restore
- Any errors encountered
- Resources that failed to restore
- Data integrity verification results

### Step 5: Clean Up

```bash
for ns in media-test pihole-test npm-test; do
  kubectl delete namespace $ns
done
```

### Quarterly DR Checklist

- [ ] Pre-test state documented
- [ ] All test namespaces created
- [ ] Multi-namespace restore completed
- [ ] All applications restored successfully
- [ ] Data integrity verified for each app
- [ ] Recovery time documented
- [ ] Any issues documented
- [ ] Test environments cleaned up
- [ ] Update runbook if needed

## Test Results Log

Maintain a log of all validation tests:

```markdown
## Test Results

### 2024-01-15 - Monthly Test Restore
- **Tester:** <name>
- **Backup Used:** daily-backup-20240115020000
- **Result:** PASS
- **Notes:** All resources restored successfully. PVC data verified.
- **Duration:** 25 minutes

### 2024-01-01 - Quarterly DR Test
- **Tester:** <name>
- **Backup Used:** weekly-backup-20231231030000
- **Result:** PASS with notes
- **Notes:** Restore completed. One ConfigMap had namespace label mismatch (non-critical).
- **Duration:** 45 minutes
- **Follow-up:** Updated backup to exclude transient labels
```

## Automated Validation (Optional)

### CronJob for Daily Validation

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: velero-backup-check
  namespace: velero
spec:
  schedule: "0 8 * * *"  # 8 AM daily
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: check
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              # Check latest backup status
              LATEST=$(kubectl get backups.velero.io -n velero \
                -l velero.io/schedule-name=daily-backup \
                --sort-by=.metadata.creationTimestamp -o name | tail -1)
              STATUS=$(kubectl get $LATEST -n velero -o jsonpath='{.status.phase}')
              if [ "$STATUS" != "Completed" ]; then
                echo "ALERT: Latest backup status is $STATUS"
                exit 1
              fi
              echo "Backup validation passed"
          restartPolicy: OnFailure
          serviceAccountName: velero
```

## Related Documentation

- [Single App Restore](./restore-single-app.md)
- [Disaster Recovery Runbook](./disaster-recovery-runbook.md)
- [Troubleshooting Guide](./troubleshooting.md)
