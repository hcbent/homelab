# etcd Local Storage Migration Plan

> **Status:** Planned  
> **Created:** 2026-02-12  
> **Estimated Duration:** ~70 minutes

## Overview

Migrate etcd data from iSCSI-backed storage to local NVMe/SSD to resolve latency issues causing control plane instability.

## Background

High etcd slow request counts caused by iSCSI storage latency:

| Node | Location | VMID | Storage | Slow Requests/hr |
|------|----------|------|---------|------------------|
| km01 | Baremetal | N/A | ✅ Local NVMe | 349 |
| km02 | pve1 | 221 | ❌ iSCSI | 802 |
| km03 | pve2 | 222 | ❌ iSCSI | 1155 |

**Root cause:** etcd requires <10ms disk latency; iSCSI was providing 23ms+

## Prerequisites

- [ ] etcd snapshot taken and copied off-cluster
- [ ] Maintenance window scheduled (~70 min)
- [ ] Access to pve1 and pve2 for disk provisioning

## Phase 0: Preparation

```bash
# Take etcd snapshot on km01
ssh bret@km01 "sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/admin-km01.pem \
  --key=/etc/ssl/etcd/ssl/admin-km01-key.pem \
  snapshot save /tmp/etcd-backup-\$(date +%Y%m%d).db"

scp km01:/tmp/etcd-backup-*.db ~/backups/
```

## Phase 1: Add Local Disks (Proxmox)

```bash
# km02 on pve1 (VMID 221)
ssh root@192.168.10.21 "qm set 221 --scsi1 local-lvm:10,iothread=1,ssd=1,discard=on"

# km03 on pve2 (VMID 222)
ssh root@192.168.10.22 "qm set 222 --scsi1 local-lvm:10,iothread=1,ssd=1,discard=on"
```

## Phase 2: Migrate km03 (worst latency first)

```bash
ssh bret@km03

# Verify new disk
lsblk  # Should see /dev/sdb

# Format
sudo mkfs.ext4 -L etcd-data /dev/sdb

# Get UUID
sudo blkid /dev/sdb

# Mount temp
sudo mkdir -p /mnt/etcd-local
sudo mount /dev/sdb /mnt/etcd-local

# Stop etcd
sudo systemctl stop etcd

# Copy data
sudo rsync -av /var/lib/etcd/ /mnt/etcd-local/
sudo chown -R etcd:etcd /mnt/etcd-local

# Swap mounts
sudo umount /mnt/etcd-local
sudo mv /var/lib/etcd /var/lib/etcd.old
sudo mkdir /var/lib/etcd
sudo mount /dev/sdb /var/lib/etcd

# Start etcd
sudo systemctl start etcd

# Verify health
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://192.168.10.234:2379,https://192.168.10.235:2379,https://192.168.10.236:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/admin-km03.pem \
  --key=/etc/ssl/etcd/ssl/admin-km03-key.pem \
  endpoint health

# Add to fstab
echo "UUID=<uuid> /var/lib/etcd ext4 defaults,noatime,discard 0 2" | sudo tee -a /etc/fstab
```

**Wait 10 minutes, verify stability before proceeding.**

## Phase 3: Migrate km02

Repeat Phase 2 steps on km02.

## Phase 4: Verification

```bash
# Check storage
ssh km02 "df -h /var/lib/etcd"
ssh km03 "df -h /var/lib/etcd"

# Check slow requests (should be <100/hour)
bash /home/bret/clawd/scripts/etcd-monitor.sh
```

## Cleanup (After 1 Week)

```bash
ssh km02 "sudo rm -rf /var/lib/etcd.old"
ssh km03 "sudo rm -rf /var/lib/etcd.old"
```

## Rollback

```bash
sudo systemctl stop etcd
sudo umount /var/lib/etcd
sudo rmdir /var/lib/etcd
sudo mv /var/lib/etcd.old /var/lib/etcd
sudo systemctl start etcd
```

## Related

- Monitoring script: `/home/bret/clawd/scripts/etcd-monitor.sh`
- Config backups: `/etc/etcd.env.backup-20260212` on all nodes
- Timeout tuning applied 2026-02-12 (ELECTION_TIMEOUT=10000, HEARTBEAT_INTERVAL=500)
