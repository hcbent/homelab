# etcd Backup Guide for Kubespray Cluster

This guide documents how to backup and restore the cluster's external etcd. etcd stores all Kubernetes cluster data including deployments, configmaps, secrets, and other resources.

## Cluster Overview

This cluster uses **external etcd** deployed by Kubespray:

| Component | Nodes | Endpoints |
|-----------|-------|-----------|
| etcd | km01, km02, km03 | https://192.168.10.234:2379, https://192.168.10.235:2379, https://192.168.10.236:2379 |

**Certificates location:** `/etc/ssl/etcd/ssl/`

## Why Backup etcd in Addition to Velero?

| Backup Type | What It Captures | Use Case |
|-------------|-----------------|----------|
| Velero | Namespace resources, PVC data | Application recovery |
| etcd | All cluster state, RBAC, CRDs, secrets | Full cluster rebuild |

## Check etcd Health

```bash
ssh km01 "sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint health"
```

Check cluster status:
```bash
ssh km01 "sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint status --write-out=table"
```

## Manual Backup

### Create On-Demand Snapshot

```bash
ssh km01 "sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  snapshot save /var/backups/etcd/snapshot-\$(date +%Y%m%d-%H%M%S).db"
```

### Verify Snapshot

```bash
ssh km01 "sudo ETCDCTL_API=3 etcdctl \
  --write-out=table \
  snapshot status /var/backups/etcd/snapshot-YYYYMMDD-HHMMSS.db"
```

### List Backups

```bash
ssh km01 "ls -la /var/backups/etcd/"
```

## Automated Daily Backups

A cron job runs daily at 1:30 AM on km01:
- **Script:** `/usr/local/bin/etcd-backup.sh`
- **Local backups:** `/var/backups/etcd/` (7 days retention)
- **Remote backups:** `192.168.1.230:/volume1/backups/etcd/` (Synology NAS)

### View Cron Job

```bash
ssh km01 "sudo crontab -l | grep etcd"
```

### Check Backup Logs

```bash
ssh km01 "sudo tail -50 /var/log/etcd-backup.log"
```

## Restoring from Snapshot

### Prerequisites

1. **Stop kube-apiserver** on all control plane nodes
2. **Stop etcd** on all nodes
3. Have the snapshot file accessible on all etcd nodes

### Restore Procedure

**Step 1: Stop Kubernetes control plane**

```bash
# On each control plane node (km01, km02, km03)
sudo systemctl stop kube-apiserver
sudo systemctl stop kube-controller-manager
sudo systemctl stop kube-scheduler
```

**Step 2: Stop etcd on all nodes**

```bash
# On each etcd node (km01, km02, km03)
sudo systemctl stop etcd
```

**Step 3: Backup current etcd data (safety)**

```bash
# On each etcd node
sudo mv /var/lib/etcd /var/lib/etcd.backup.$(date +%Y%m%d)
```

**Step 4: Restore snapshot on each node**

Copy the snapshot to all etcd nodes, then restore:

```bash
# On km01
sudo ETCDCTL_API=3 etcdctl snapshot restore /var/backups/etcd/snapshot-YYYYMMDD-HHMMSS.db \
  --name km01 \
  --initial-cluster km01=https://192.168.10.234:2380,km02=https://192.168.10.235:2380,km03=https://192.168.10.236:2380 \
  --initial-cluster-token etcd-cluster-1 \
  --initial-advertise-peer-urls https://192.168.10.234:2380 \
  --data-dir=/var/lib/etcd

# On km02
sudo ETCDCTL_API=3 etcdctl snapshot restore /var/backups/etcd/snapshot-YYYYMMDD-HHMMSS.db \
  --name km02 \
  --initial-cluster km01=https://192.168.10.234:2380,km02=https://192.168.10.235:2380,km03=https://192.168.10.236:2380 \
  --initial-cluster-token etcd-cluster-1 \
  --initial-advertise-peer-urls https://192.168.10.235:2380 \
  --data-dir=/var/lib/etcd

# On km03
sudo ETCDCTL_API=3 etcdctl snapshot restore /var/backups/etcd/snapshot-YYYYMMDD-HHMMSS.db \
  --name km03 \
  --initial-cluster km01=https://192.168.10.234:2380,km02=https://192.168.10.235:2380,km03=https://192.168.10.236:2380 \
  --initial-cluster-token etcd-cluster-1 \
  --initial-advertise-peer-urls https://192.168.10.236:2380 \
  --data-dir=/var/lib/etcd
```

**Step 5: Fix permissions**

```bash
# On each etcd node
sudo chown -R etcd:etcd /var/lib/etcd
```

**Step 6: Start etcd**

```bash
# On each etcd node
sudo systemctl start etcd
```

**Step 7: Verify etcd cluster**

```bash
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  member list
```

**Step 8: Start Kubernetes control plane**

```bash
# On each control plane node
sudo systemctl start kube-apiserver
sudo systemctl start kube-controller-manager
sudo systemctl start kube-scheduler
```

**Step 9: Verify cluster**

```bash
kubectl get nodes
kubectl get pods -A
```

## Pre-Upgrade Backup

Always create a snapshot before cluster upgrades:

```bash
ssh km01 "sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  snapshot save /var/backups/etcd/pre-upgrade-\$(date +%Y%m%d-%H%M%S).db"
```

## Troubleshooting

### Snapshot Fails with Timeout

```bash
# Check etcd health
ssh km01 "sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem \
  endpoint health"

# Check etcd logs
ssh km01 "sudo journalctl -u etcd -n 50"
```

### Certificate Errors

Verify certificates exist and are readable:

```bash
ssh km01 "sudo ls -la /etc/ssl/etcd/ssl/"
```

### Restore Fails

1. Ensure etcd is stopped on all nodes
2. Ensure /var/lib/etcd is empty or moved
3. Check snapshot integrity with `etcdctl snapshot status`

## Related Documentation

- [Disaster Recovery Runbook](./disaster-recovery-runbook.md) - Full cluster recovery
- [Velero Restore Guide](./restore-single-app.md) - Application-level recovery
