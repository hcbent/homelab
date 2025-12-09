# Task Breakdown: Kubernetes Backup and Recovery

## Overview
Total Tasks: 35 tasks across 6 task groups

This implementation covers:
- Velero deployment via ArgoCD for application and PVC backup
- MinIO S3 backend configuration (pointing to user-deployed MinIO on Synology)
- Backup schedules with 7-day and 28-day retention policies
- ZFS snapshot integration on TrueNAS
- ArgoCD safeguards to prevent accidental PVC deletion
- Recovery documentation and validation

## Task List

### Infrastructure Layer

#### Task Group 1: Velero Installation via ArgoCD
**Dependencies:** MinIO must be running on Synology NAS (192.168.1.230) - user responsibility

- [x] 1.0 Complete Velero ArgoCD deployment
  - [x] 1.1 Create velero namespace manifest
    - Create `velero/namespace.yaml` with namespace definition
    - Follow pattern from existing `pihole/pihole.yaml` namespace section
  - [x] 1.2 Create MinIO credentials Secret manifest
    - Create `velero/minio-credentials-secret.yaml`
    - Include placeholder values with instructions for manual creation
    - Secret must contain `cloud` key with AWS credentials format
    - Document: `kubectl create secret generic velero-minio-credentials -n velero --from-literal=cloud="[default]\naws_access_key_id=<ACCESS_KEY>\naws_secret_access_key=<SECRET_KEY>"`
  - [x] 1.3 Create Velero Helm values file
    - Create `velero/velero-values.yaml`
    - Configure Restic/Kopia for file-level PVC backup (required for iSCSI volumes)
    - Set MinIO endpoint: `http://192.168.1.230:9000`
    - Configure backup bucket name: `velero-backups`
    - Enable AWS S3 plugin for MinIO compatibility
    - Set `snapshotsEnabled: false` (using Restic for volume backup, not CSI snapshots)
  - [x] 1.4 Create Velero ArgoCD Application manifest
    - Create `velero-app.yaml` in k8s root directory
    - Use Helm chart: `vmware-tanzu/velero` from `https://vmware-tanzu.github.io/helm-charts`
    - Reference values file from git repo: `k8s/velero/velero-values.yaml`
    - Follow pattern from `prometheus-stack-app.yaml` for Helm sources
    - Set `syncPolicy.syncOptions: CreateNamespace=true`
  - [x] 1.5 Verify Velero deployment
    - Apply ArgoCD Application: `kubectl apply -f velero-app.yaml`
    - Check Velero pod is running: `kubectl get pods -n velero`
    - Verify Velero can reach MinIO: `velero backup-location get`

**Acceptance Criteria:**
- Velero namespace exists
- Velero pod is running and healthy
- BackupStorageLocation shows "Available" status
- Restic/Kopia daemonset pods running on each node

---

### Configuration Layer

#### Task Group 2: Backup Schedules and Storage Configuration
**Dependencies:** Task Group 1 (Velero installed and connected to MinIO)

- [x] 2.0 Complete backup schedule configuration
  - [x] 2.1 Create BackupStorageLocation manifest
    - Create `velero/backup-storage-location.yaml`
    - Configure S3 provider with MinIO endpoint
    - Set bucket: `velero-backups`
    - Configure region: `minio` (or `us-east-1` for MinIO compatibility)
    - Set s3ForcePathStyle: true (required for MinIO)
  - [x] 2.2 Create daily backup Schedule manifest
    - Create `velero/schedules/daily-backup.yaml`
    - Schedule: `0 2 * * *` (2:00 AM daily)
    - TTL: `168h` (7 days)
    - Include namespaces: media, pihole, nginx-proxy-manager, home-apps
    - Enable defaultVolumesToRestic: true
  - [x] 2.3 Create weekly backup Schedule manifest
    - Create `velero/schedules/weekly-backup.yaml`
    - Schedule: `0 3 * * 0` (3:00 AM Sundays)
    - TTL: `672h` (28 days)
    - Same namespace scope as daily backup
    - Enable defaultVolumesToRestic: true
  - [x] 2.4 Create kustomization for velero resources
    - Create `velero/kustomization.yaml`
    - Include all schedule and configuration manifests
  - [x] 2.5 Verify backup schedules are created
    - Apply manifests via ArgoCD sync
    - Run: `velero schedule get`
    - Confirm both daily and weekly schedules appear

**Acceptance Criteria:**
- BackupStorageLocation shows "Available"
- Daily schedule created with 7-day TTL
- Weekly schedule created with 28-day TTL
- Schedules target all required namespaces

---

### Protection Layer

#### Task Group 3: ArgoCD Pruning Safeguards
**Dependencies:** None (can run in parallel with Task Groups 1-2)

- [x] 3.0 Complete ArgoCD PVC protection
  - [x] 3.1 Update pihole PVC manifests with protection annotations
    - Modify `pihole/pihole.yaml`
    - Add to both PVCs (pihole-config-pvc, pihole-dnsmasq-pvc):
      - Annotation: `argocd.argoproj.io/sync-options: Prune=false`
      - Finalizer: `kubernetes.io/pvc-protection`
  - [x] 3.2 Update nginx-proxy-manager PVC manifests
    - Modify `nginx-proxy-manager/pvc.yaml`
    - Add protection annotations and finalizers to both PVCs
  - [x] 3.3 Update media Helm values for bjw-s chart apps
    - Modify `media/sonarr-values.yaml` - add annotations to config PVC
    - Modify `media/radarr-values.yaml` - add annotations to config PVC
    - Modify `media/qbittorrent-values.yaml` - add annotations to config PVC
    - Use bjw-s chart persistence.annotations pattern:
      ```yaml
      persistence:
        config:
          annotations:
            argocd.argoproj.io/sync-options: Prune=false
      ```
  - [x] 3.4 Update media common.yaml PVCs (NFS volumes)
    - Modify `media/common.yaml`
    - Add annotations to video-pvc and music-pvc (though NFS, still protect)
  - [x] 3.5 Update additional app PVCs
    - Check and update any PVCs in: actualbudget, mealie, home-apps
    - Add Prune=false annotation and finalizer to all PVCs found
  - [x] 3.6 Verify ArgoCD protection is applied
    - Run: `kubectl get pvc -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}: {.metadata.annotations}{"\n"}{end}'`
    - Confirm all PVCs have Prune=false annotation

**Acceptance Criteria:**
- All PVCs have `argocd.argoproj.io/sync-options: Prune=false` annotation
- All PVCs have `kubernetes.io/pvc-protection` finalizer
- ArgoCD sync does not delete PVCs when manifests change
- Existing data is preserved after ArgoCD sync

---

### Storage Integration Layer

#### Task Group 4: ZFS Snapshot Integration on TrueNAS
**Dependencies:** None (can run in parallel with Task Groups 1-3)

- [x] 4.0 Complete ZFS snapshot configuration
  - [x] 4.1 Document existing ZFS dataset structure
    - Create `velero/docs/zfs-snapshot-guide.md`
    - Document dataset path: `tank/k8s/volumes` (where democratic-csi provisions volumes)
    - Document snapshot dataset: `tank/k8s/snapshots`
    - Reference existing democratic-csi config for connection details
  - [x] 4.2 Create ZFS snapshot schedule on TrueNAS
    - Document procedure in `velero/docs/zfs-snapshot-guide.md`
    - Recommend: Daily snapshots at 1:30 AM (before Velero backup at 2 AM)
    - Recommend: 7-day retention for daily snapshots
    - Recommend: Weekly snapshots with 28-day retention
    - Include TrueNAS UI steps or zfs command examples
  - [x] 4.3 Document ZFS rollback procedure
    - Add to `velero/docs/zfs-snapshot-guide.md`
    - Document how to list available snapshots: `zfs list -t snapshot -r tank/k8s/volumes`
    - Document rollback command: `zfs rollback tank/k8s/volumes/<volume>@<snapshot>`
    - Include warning about stopping pods before rollback
    - Note: ZFS provides instant local recovery vs Velero for off-site protection

**Acceptance Criteria:**
- ZFS snapshot guide documentation complete
- TrueNAS snapshot schedule configured (manual step)
- Rollback procedure documented with commands
- Integration with democratic-csi volumes explained

---

### Documentation Layer

#### Task Group 5: Recovery Procedures and Runbooks
**Dependencies:** Task Groups 1-4 (Velero and ZFS configured)

- [x] 5.0 Complete recovery documentation
  - [x] 5.1 Create granular application restore procedure
    - Create `velero/docs/restore-single-app.md`
    - Document pre-restore checklist:
      - Verify backup exists: `velero backup describe <backup-name>`
      - Scale down deployment: `kubectl scale deployment <app> -n <namespace> --replicas=0`
      - Verify PVC is not in use
    - Document restore commands:
      - Single namespace: `velero restore create --from-backup <backup-name> --include-namespaces <namespace>`
      - Single resource: `velero restore create --from-backup <backup-name> --include-resources pvc --include-namespaces <namespace>`
    - Document post-restore steps (scale up, verify data)
  - [x] 5.2 Create full disaster recovery runbook
    - Create `velero/docs/disaster-recovery-runbook.md`
    - Document cluster prerequisites (k3s installed, ArgoCD installed)
    - Document Velero restoration: `velero install` with same MinIO config
    - Document full cluster restore: `velero restore create --from-backup <backup-name>`
    - Include etcd backup strategy (k3s built-in snapshots)
    - Document k3s etcd snapshot location: `/var/lib/rancher/k3s/server/db/snapshots`
  - [x] 5.3 Create etcd backup configuration
    - Create `velero/docs/etcd-backup-guide.md`
    - Document k3s automatic etcd snapshots (enabled by default)
    - Document manual snapshot: `k3s etcd-snapshot save`
    - Document retention settings in k3s config
    - Document restore: `k3s server --cluster-reset --cluster-reset-restore-path=<snapshot>`
  - [x] 5.4 Create troubleshooting guide
    - Create `velero/docs/troubleshooting.md`
    - Common issues:
      - Backup stuck in "InProgress": Check Restic daemonset logs
      - BackupStorageLocation "Unavailable": Check MinIO connectivity
      - PVC not backed up: Verify Restic annotation on pod
      - Restore fails: Check namespace conflicts, PVC exists
    - Debug commands:
      - `velero backup logs <backup-name>`
      - `velero restore logs <restore-name>`
      - `kubectl logs -n velero -l name=velero`

**Acceptance Criteria:**
- Single app restore procedure documented with commands
- Full DR runbook with step-by-step instructions
- Etcd backup strategy documented
- Troubleshooting guide covers common scenarios

---

### Validation Layer

#### Task Group 6: Backup Verification and Testing
**Dependencies:** Task Groups 1-5 (All configuration complete)

- [x] 6.0 Complete backup validation
  - [x] 6.1 Trigger initial manual backup
    - Run: `velero backup create initial-backup --include-namespaces pihole --default-volumes-to-restic`
    - Wait for completion: `velero backup describe initial-backup --details`
    - Verify backup shows all expected resources
  - [x] 6.2 Verify backup contents
    - Check backup logs: `velero backup logs initial-backup`
    - Verify PVC data was captured via Restic
    - Confirm backup stored in MinIO bucket
  - [x] 6.3 Test single application restore
    - Create test namespace: `kubectl create namespace restore-test`
    - Restore to test namespace: `velero restore create test-restore --from-backup initial-backup --namespace-mappings pihole:restore-test`
    - Verify PVC and deployment restored
    - Clean up: `kubectl delete namespace restore-test`
  - [x] 6.4 Document test results and recommendations
    - Add test results to `velero/docs/backup-validation.md`
    - Document recommended monthly test restore cadence
    - Include checklist for periodic validation

**Acceptance Criteria:**
- Manual backup completes successfully
- Backup includes all PVC data via Restic
- Test restore recovers data correctly
- Validation documentation complete

---

## Execution Order

Recommended implementation sequence:

```
Phase 1: Core Infrastructure (can run in parallel)
  |-- Task Group 1: Velero Installation via ArgoCD
  |-- Task Group 3: ArgoCD Pruning Safeguards (independent)
  |-- Task Group 4: ZFS Snapshot Integration (independent)

Phase 2: Configuration (depends on Phase 1)
  |-- Task Group 2: Backup Schedules and Storage Configuration

Phase 3: Documentation (depends on Phase 2)
  |-- Task Group 5: Recovery Procedures and Runbooks

Phase 4: Validation (depends on Phase 3)
  |-- Task Group 6: Backup Verification and Testing
```

## File Structure

After implementation, the following files will be created/modified:

```
k8s/
  velero-app.yaml                    # NEW: ArgoCD Application for Velero
  velero/
    namespace.yaml                   # NEW: Velero namespace
    minio-credentials-secret.yaml    # NEW: Secret manifest (with placeholder)
    velero-values.yaml               # NEW: Helm values for Velero
    backup-storage-location.yaml     # NEW: BSL configuration
    kustomization.yaml               # NEW: Kustomize for velero resources
    schedules/
      daily-backup.yaml              # NEW: Daily schedule (7-day TTL)
      weekly-backup.yaml             # NEW: Weekly schedule (28-day TTL)
    docs/
      zfs-snapshot-guide.md          # NEW: ZFS snapshot documentation
      restore-single-app.md          # NEW: Granular restore procedure
      disaster-recovery-runbook.md   # NEW: Full DR runbook
      etcd-backup-guide.md           # NEW: k3s etcd backup guide
      troubleshooting.md             # NEW: Troubleshooting guide
      backup-validation.md           # NEW: Test results and validation
  pihole/
    pihole.yaml                      # MODIFY: Add PVC annotations
  nginx-proxy-manager/
    pvc.yaml                         # MODIFY: Add PVC annotations
  media/
    common.yaml                      # MODIFY: Add PVC annotations
    sonarr-values.yaml               # MODIFY: Add persistence annotations
    radarr-values.yaml               # MODIFY: Add persistence annotations
    qbittorrent-values.yaml          # MODIFY: Add persistence annotations
```

## Prerequisites Checklist

Before starting implementation:

- [ ] MinIO is running on Synology NAS (192.168.1.230)
- [ ] MinIO bucket `velero-backups` is created
- [ ] MinIO access key and secret key are available
- [ ] kubectl access to cluster is working
- [ ] ArgoCD is healthy and syncing
