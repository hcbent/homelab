# etcd Backup Guide for k3s

This guide documents how to backup and restore the k3s cluster state using etcd snapshots. etcd stores all Kubernetes cluster data including deployments, configmaps, secrets, and other resources.

## Overview

k3s uses SQLite by default for single-node clusters, or embedded etcd for HA clusters. This guide covers both scenarios.

**Why backup etcd in addition to Velero?**

| Backup Type | What It Captures | Use Case |
|-------------|-----------------|----------|
| Velero | Namespace resources, PVC data | Application recovery |
| etcd | All cluster state, RBAC, CRDs | Cluster rebuild |

## k3s Storage Mode Detection

Check which storage backend k3s is using:

```bash
# Check k3s configuration
sudo cat /etc/rancher/k3s/config.yaml

# Or check the running process
ps aux | grep k3s | grep -E "(etcd|datastore)"

# Check if etcd is running
sudo ls /var/lib/rancher/k3s/server/db/
# If etcd/ directory exists, using embedded etcd
# If state.db exists, using SQLite
```

## Automatic Snapshots (k3s Default)

k3s automatically takes etcd snapshots. Configuration is in k3s server flags or config file.

### Default Snapshot Settings

- **Location:** `/var/lib/rancher/k3s/server/db/snapshots/`
- **Frequency:** Every 12 hours (etcd) or on graceful shutdown (SQLite)
- **Retention:** 5 snapshots

### View Existing Snapshots

```bash
# List local snapshots
sudo ls -la /var/lib/rancher/k3s/server/db/snapshots/

# Example output:
# etcd-snapshot-k3s-server-1709856000
# etcd-snapshot-k3s-server-1709899200
```

## Configuring Snapshot Schedule

### Option 1: k3s Config File

Edit `/etc/rancher/k3s/config.yaml`:

```yaml
# etcd snapshot configuration
etcd-snapshot-schedule-cron: "0 */6 * * *"  # Every 6 hours
etcd-snapshot-retention: 10                  # Keep 10 snapshots
etcd-snapshot-dir: /var/lib/rancher/k3s/server/db/snapshots
```

Restart k3s:
```bash
sudo systemctl restart k3s
```

### Option 2: Server Flags

Start k3s with snapshot flags:

```bash
k3s server \
  --etcd-snapshot-schedule-cron="0 */6 * * *" \
  --etcd-snapshot-retention=10
```

### Option 3: S3-Compatible Backup (MinIO)

Configure k3s to store snapshots directly on MinIO:

```yaml
# /etc/rancher/k3s/config.yaml
etcd-s3: true
etcd-s3-endpoint: "192.168.1.230:9000"
etcd-s3-bucket: "k3s-etcd-snapshots"
etcd-s3-access-key: "<MINIO_ACCESS_KEY>"
etcd-s3-secret-key: "<MINIO_SECRET_KEY>"
etcd-s3-skip-ssl-verify: true  # For HTTP endpoint
etcd-snapshot-schedule-cron: "0 */6 * * *"
etcd-snapshot-retention: 10
```

## Manual Snapshot Creation

### Create On-Demand Snapshot

```bash
# Take immediate snapshot (saved locally)
sudo k3s etcd-snapshot save

# Take snapshot with custom name
sudo k3s etcd-snapshot save --name pre-upgrade-$(date +%Y%m%d)

# Take snapshot and upload to S3
sudo k3s etcd-snapshot save \
  --s3 \
  --s3-endpoint "192.168.1.230:9000" \
  --s3-bucket "k3s-etcd-snapshots" \
  --s3-access-key "<ACCESS_KEY>" \
  --s3-secret-key "<SECRET_KEY>"
```

### List Available Snapshots

```bash
# List local snapshots
sudo k3s etcd-snapshot ls

# List S3 snapshots
sudo k3s etcd-snapshot ls \
  --s3 \
  --s3-endpoint "192.168.1.230:9000" \
  --s3-bucket "k3s-etcd-snapshots" \
  --s3-access-key "<ACCESS_KEY>" \
  --s3-secret-key "<SECRET_KEY>"
```

### Delete Old Snapshots

```bash
# Delete specific snapshot
sudo k3s etcd-snapshot delete <snapshot-name>

# Prune to retention count
sudo k3s etcd-snapshot prune --snapshot-retention 5
```

## Restoring from etcd Snapshot

### Prerequisites

1. k3s service must be stopped
2. All worker nodes should be disconnected
3. Have the snapshot file accessible

### Restore Procedure

**Step 1: Stop k3s on all nodes**

```bash
# On server node
sudo systemctl stop k3s

# On worker nodes
sudo systemctl stop k3s-agent
```

**Step 2: Identify snapshot to restore**

```bash
# List snapshots
ls -la /var/lib/rancher/k3s/server/db/snapshots/

# Or find most recent
ls -t /var/lib/rancher/k3s/server/db/snapshots/ | head -1
```

**Step 3: Restore from snapshot**

```bash
# Restore from local snapshot
sudo k3s server \
  --cluster-reset \
  --cluster-reset-restore-path=/var/lib/rancher/k3s/server/db/snapshots/<snapshot-name>

# Restore from S3 snapshot
sudo k3s server \
  --cluster-reset \
  --etcd-s3 \
  --etcd-s3-endpoint "192.168.1.230:9000" \
  --etcd-s3-bucket "k3s-etcd-snapshots" \
  --etcd-s3-access-key "<ACCESS_KEY>" \
  --etcd-s3-secret-key "<SECRET_KEY>" \
  --cluster-reset-restore-path=<snapshot-name>
```

**Step 4: Start k3s normally**

```bash
# The restore command will exit after completion
# Start k3s normally
sudo systemctl start k3s

# Verify cluster is running
sudo k3s kubectl get nodes
```

**Step 5: Rejoin worker nodes**

```bash
# Get new token (token may have changed)
sudo cat /var/lib/rancher/k3s/server/node-token

# On worker nodes, restart with new token if needed
sudo systemctl restart k3s-agent
```

## SQLite Backup (Non-HA Clusters)

If using SQLite instead of etcd:

### Backup SQLite Database

```bash
# Stop k3s to ensure consistent backup
sudo systemctl stop k3s

# Copy SQLite database
sudo cp /var/lib/rancher/k3s/server/db/state.db \
  /backup/k3s-state-$(date +%Y%m%d).db

# Start k3s
sudo systemctl start k3s
```

### Restore SQLite Database

```bash
# Stop k3s
sudo systemctl stop k3s

# Replace database
sudo cp /backup/k3s-state-YYYYMMDD.db \
  /var/lib/rancher/k3s/server/db/state.db

# Fix permissions
sudo chown root:root /var/lib/rancher/k3s/server/db/state.db

# Start k3s
sudo systemctl start k3s
```

## Backup Best Practices

### Recommended Backup Schedule

```yaml
# /etc/rancher/k3s/config.yaml

# Take snapshots every 6 hours
etcd-snapshot-schedule-cron: "0 */6 * * *"

# Keep 2 days of snapshots locally (8 snapshots at 6-hour intervals)
etcd-snapshot-retention: 8

# Also backup to S3 for off-server protection
etcd-s3: true
etcd-s3-endpoint: "192.168.1.230:9000"
etcd-s3-bucket: "k3s-etcd-snapshots"
etcd-s3-access-key: "<ACCESS_KEY>"
etcd-s3-secret-key: "<SECRET_KEY>"
```

### Pre-Upgrade Backup

Always create a snapshot before k3s upgrades:

```bash
# Take named snapshot
sudo k3s etcd-snapshot save --name pre-upgrade-$(date +%Y%m%d)

# Verify it was created
sudo k3s etcd-snapshot ls | grep pre-upgrade
```

### Copy Snapshots Off-Server

Even without S3 integration, copy snapshots to external storage:

```bash
# Copy to NFS/backup location
sudo cp /var/lib/rancher/k3s/server/db/snapshots/* \
  /mnt/backup/k3s-snapshots/

# Or rsync to remote server
sudo rsync -av /var/lib/rancher/k3s/server/db/snapshots/ \
  backup-server:/backups/k3s/
```

## Disaster Recovery with etcd

When recovering a cluster from scratch:

1. **Install k3s** (without starting):
   ```bash
   curl -sfL https://get.k3s.io | INSTALL_K3S_SKIP_START=true sh -
   ```

2. **Copy snapshot to server**:
   ```bash
   sudo mkdir -p /var/lib/rancher/k3s/server/db/snapshots
   sudo cp /backup/etcd-snapshot-latest /var/lib/rancher/k3s/server/db/snapshots/
   ```

3. **Restore and start**:
   ```bash
   sudo k3s server --cluster-reset \
     --cluster-reset-restore-path=/var/lib/rancher/k3s/server/db/snapshots/etcd-snapshot-latest
   ```

## Troubleshooting

### Snapshot Fails with Timeout

```bash
# Check etcd health
sudo k3s kubectl get cs

# Check k3s server logs
sudo journalctl -u k3s -f
```

### Cannot Find Snapshots After Restore

Snapshots are in different locations depending on configuration:

```bash
# Check default location
ls /var/lib/rancher/k3s/server/db/snapshots/

# Check custom location (from config)
grep etcd-snapshot-dir /etc/rancher/k3s/config.yaml
```

### Worker Nodes Cannot Rejoin

After restore, worker nodes need the new token:

```bash
# On server: Get new token
sudo cat /var/lib/rancher/k3s/server/node-token

# On worker: Update token and restart
# Edit /etc/systemd/system/k3s-agent.service.env
# Update K3S_TOKEN value
sudo systemctl daemon-reload
sudo systemctl restart k3s-agent
```

## Related Documentation

- [Disaster Recovery Runbook](./disaster-recovery-runbook.md) - Full cluster recovery
- [Velero Restore Guide](./restore-single-app.md) - Application-level recovery
- [k3s Documentation](https://docs.k3s.io/datastore/backup-restore) - Official k3s backup docs
