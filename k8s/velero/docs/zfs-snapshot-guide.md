# ZFS Snapshot Guide for TrueNAS

This guide documents how ZFS snapshots provide secondary backup protection for Kubernetes persistent volumes provisioned by democratic-csi on TrueNAS.

## Overview

ZFS snapshots provide instant, space-efficient point-in-time copies of data. They serve as a secondary protection layer alongside Velero backups stored on MinIO (Synology NAS).

**Why both Velero and ZFS snapshots?**

| Feature | Velero (MinIO) | ZFS Snapshots |
|---------|----------------|---------------|
| Location | Off-server (Synology) | Local (TrueNAS) |
| Recovery speed | Minutes | Instant |
| Protection from | Server failure, ZFS corruption | Accidental deletion, app issues |
| Granularity | Full PVC restore | Volume-level rollback |

## ZFS Dataset Structure

Democratic-csi provisions iSCSI volumes on TrueNAS using the following datasets:

```
tank/
  k8s/
    volumes/       <- Where PVCs are created as ZFS volumes
    snapshots/     <- Where detached snapshots are stored (if using CSI snapshots)
```

### Connection Details (from democratic-csi config)

- **TrueNAS Host:** truenas.lab.thewortmans.org
- **Dataset Path:** tank/k8s/volumes
- **Snapshot Dataset:** tank/k8s/snapshots
- **iSCSI Portal:** truenas.lab.thewortmans.org:3260
- **Storage Class:** freenas-iscsi-csi

## Configuring ZFS Snapshot Schedule on TrueNAS

### Option 1: TrueNAS SCALE Web UI

1. Navigate to **Data Protection** > **Periodic Snapshot Tasks**
2. Click **Add**
3. Configure the snapshot task:

**Daily Snapshots:**
- **Dataset:** `tank/k8s/volumes`
- **Recursive:** Yes (to capture all PVC volumes)
- **Exclude:** Leave empty
- **Snapshot Lifetime:** 7 Days
- **Naming Schema:** `auto-%Y-%m-%d_%H-%M`
- **Schedule:** Daily at 1:30 AM (30 minutes before Velero backup at 2 AM)
- **Allow Taking Empty Snapshots:** No
- **Enabled:** Yes

**Weekly Snapshots:**
- **Dataset:** `tank/k8s/volumes`
- **Recursive:** Yes
- **Snapshot Lifetime:** 28 Days
- **Naming Schema:** `weekly-%Y-%m-%d_%H-%M`
- **Schedule:** Weekly on Sunday at 1:00 AM
- **Enabled:** Yes

### Option 2: SSH/CLI Commands

Connect to TrueNAS via SSH and create snapshot tasks:

```bash
# List current datasets
zfs list -t filesystem -r tank/k8s

# Create manual snapshot of all k8s volumes
zfs snapshot -r tank/k8s/volumes@manual-$(date +%Y-%m-%d_%H-%M)

# List existing snapshots
zfs list -t snapshot -r tank/k8s/volumes
```

For automated snapshots via cron (alternative to TrueNAS UI):

```bash
# Add to crontab on TrueNAS
# Daily snapshot at 1:30 AM
30 1 * * * /usr/sbin/zfs snapshot -r tank/k8s/volumes@auto-$(date +\%Y-\%m-\%d)

# Weekly snapshot on Sunday at 1:00 AM
0 1 * * 0 /usr/sbin/zfs snapshot -r tank/k8s/volumes@weekly-$(date +\%Y-\%m-\%d)
```

## Managing Snapshots

### List Available Snapshots

```bash
# List all snapshots for k8s volumes
zfs list -t snapshot -r tank/k8s/volumes

# List snapshots with creation date and size
zfs list -t snapshot -r tank/k8s/volumes -o name,creation,used,refer

# Find snapshots for a specific volume (e.g., sonarr config)
zfs list -t snapshot tank/k8s/volumes | grep sonarr
```

### Snapshot Retention

Old snapshots should be cleaned up automatically by TrueNAS periodic snapshot tasks. Manual cleanup:

```bash
# Remove a specific snapshot
zfs destroy tank/k8s/volumes/pvc-abc123@auto-2024-01-01

# Remove all snapshots older than 30 days (use with caution)
zfs list -t snapshot -r tank/k8s/volumes -o name -H | \
  while read snap; do
    # Check age and destroy if old
    # (implement date comparison logic)
  done
```

## ZFS Rollback Procedure

### Prerequisites

**IMPORTANT:** Before performing a ZFS rollback:

1. **Stop the application** using the volume to prevent data corruption
2. **Identify the correct snapshot** to restore
3. **Understand that rollback destroys all data after the snapshot**

### Step-by-Step Rollback

1. **Scale down the application:**

```bash
# Example: Scale down Sonarr
kubectl scale deployment sonarr -n media --replicas=0

# Verify pod is terminated
kubectl get pods -n media -l app.kubernetes.io/name=sonarr
```

2. **Identify the volume to rollback:**

```bash
# Find the PVC
kubectl get pvc -n media

# Get the PV name
kubectl get pvc sonarr-config -n media -o jsonpath='{.spec.volumeName}'
# Example output: pvc-abc123-def456-...
```

3. **Find available snapshots on TrueNAS:**

```bash
# SSH to TrueNAS
ssh root@truenas.lab.thewortmans.org

# List snapshots for the volume
zfs list -t snapshot tank/k8s/volumes/pvc-abc123-def456 -o name,creation
```

4. **Perform the rollback:**

```bash
# WARNING: This destroys all data after the snapshot point
zfs rollback tank/k8s/volumes/pvc-abc123-def456@auto-2024-01-15
```

If the snapshot is not the most recent, you must use `-r` flag (which destroys intermediate snapshots):

```bash
zfs rollback -r tank/k8s/volumes/pvc-abc123-def456@auto-2024-01-10
```

5. **Scale up the application:**

```bash
kubectl scale deployment sonarr -n media --replicas=1

# Verify pod is running
kubectl get pods -n media -l app.kubernetes.io/name=sonarr
```

6. **Verify data restoration:**
   - Access the application and confirm data is restored
   - Check application logs for errors

### Rollback Caveats

- **Rollback removes all data after the snapshot point** - there is no undo
- **Cannot rollback to older snapshot without `-r` flag** - this destroys all intermediate snapshots
- **Application must be stopped** during rollback to prevent corruption
- **iSCSI sessions may need to be refreshed** - if issues occur, disconnect/reconnect the iSCSI target

## Comparison: ZFS Rollback vs Velero Restore

| Scenario | Use ZFS Rollback | Use Velero Restore |
|----------|------------------|-------------------|
| Accidental file deletion (within 24h) | Yes | Slower but works |
| Application corruption | Yes | Yes |
| TrueNAS failure | No | Yes (data on Synology) |
| Need to restore to different namespace | No | Yes |
| Cluster-wide disaster | No | Yes |
| Need specific resource restore | No | Yes (more granular) |

## Troubleshooting

### Snapshot Not Appearing

```bash
# Verify dataset exists
zfs list tank/k8s/volumes

# Check if snapshot task is enabled in TrueNAS UI
# Data Protection > Periodic Snapshot Tasks

# Manually trigger a snapshot to test
zfs snapshot -r tank/k8s/volumes@test-$(date +%Y-%m-%d_%H-%M)
```

### Rollback Fails with "dataset is busy"

The iSCSI target is still in use:

1. Ensure Kubernetes pod is terminated
2. Check TrueNAS Sharing > iSCSI > Targets for active connections
3. Force disconnect if necessary (may cause data issues)

### Cannot Find PVC Volume on TrueNAS

```bash
# List all ZFS volumes under k8s
zfs list -r tank/k8s/volumes

# Match with Kubernetes PV name
kubectl get pv -o wide
```
