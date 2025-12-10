# Specification: Kubernetes Backup and Recovery

## Goal

Implement a comprehensive backup and recovery solution using Velero with MinIO storage on Synology NAS, plus ZFS snapshots on TrueNAS as secondary protection, to enable both granular application recovery and full disaster recovery while preventing accidental data loss from ArgoCD pruning.

## User Stories

- As a homelab administrator, I want automated daily backups of all PVC data and cluster state so that I can recover from disasters or human error within 24 hours
- As a homelab administrator, I want to restore a single application's data without affecting other services so that I can quickly fix accidental deletions

## Specific Requirements

**Velero Installation via ArgoCD**
- Deploy Velero using Helm chart via ArgoCD Application resource
- Configure Velero with Restic/Kopia for file-level PVC backup (required for iSCSI volumes from democratic-csi)
- Use the existing ArgoCD pattern from prometheus-stack-app.yaml and nginx-proxy-manager-app.yaml as templates
- Create velero namespace for the deployment
- Include AWS S3 plugin for MinIO compatibility

**MinIO S3-Compatible Storage Backend**
- User will deploy MinIO on Synology NAS (192.168.1.230) prior to Velero configuration
- Configure Velero BackupStorageLocation pointing to MinIO endpoint
- Create Kubernetes Secret with MinIO access credentials
- Use a dedicated bucket for Velero backups (e.g., velero-backups)
- Verify S3 connectivity before enabling scheduled backups

**Backup Schedules and Retention**
- Create Velero Schedule resource for daily backups at a consistent time (e.g., 2:00 AM)
- Configure TTL of 7 days for daily backups
- Create separate weekly backup Schedule (e.g., Sundays) with 28-day TTL for 4-week retention
- Include all namespaces with PVCs: media, pihole, nginx-proxy-manager, actualbudget, mealie, and others
- Use label selectors or namespace selectors to target backup scope

**ZFS Snapshot Integration on TrueNAS**
- Leverage TrueNAS ZFS for fast local snapshots as secondary protection layer
- Configure ZFS snapshot schedule on tank/k8s/volumes dataset (where democratic-csi provisions volumes)
- Snapshots provide instant rollback for iSCSI volumes without needing full Velero restore
- Document manual ZFS rollback procedure as alternative recovery path
- This provides "belt and suspenders" approach with Synology as off-site copy

**Granular Application Recovery**
- Document procedure for restoring single namespace or application using `velero restore create`
- Use `--include-namespaces` flag to target specific applications
- Use `--include-resources` flag for selective resource restoration
- Test and validate restore of PVC-backed applications (Sonarr, Radarr, Pi-hole)
- Include pre-restore checklist (scale down deployment, verify backup integrity)

**Full Disaster Recovery**
- Document procedure for full cluster restore from Velero backups
- Include etcd backup strategy using k3s built-in snapshot capabilities (if cluster is k3s)
- Create recovery runbook with step-by-step instructions
- Validate that cluster state (namespaces, configmaps, secrets) can be restored alongside PVC data

**ArgoCD Pruning Safeguards**
- Add `argocd.argoproj.io/sync-options: Prune=false` annotation to all PVC resources
- Add finalizers to PVCs to prevent immediate deletion: `kubernetes.io/pvc-protection`
- Update existing manifests: pihole/pihole.yaml, nginx-proxy-manager/pvc.yaml, media/common.yaml
- Update Helm values for apps using bjw-s chart (sonarr, radarr, qbittorrent) to include annotations
- Document the protection mechanism in the codebase

**Backup Verification and Testing**
- Create test restore procedure to validate backup integrity
- Document how to verify backup completion using `velero backup describe`
- Include troubleshooting steps for common backup failures
- Establish periodic test restore cadence (recommend monthly)

## Visual Design

No visual assets provided.

## Existing Code to Leverage

**ArgoCD Application Pattern (prometheus-stack-app.yaml, nginx-proxy-manager-app.yaml)**
- Standard ArgoCD Application resource structure for Helm chart deployments
- Use `sources` array for Helm charts with external values
- syncPolicy configuration with `CreateNamespace` and `automated` sync options
- Apply same pattern for Velero ArgoCD Application

**democratic-csi Configuration (democratic-csi/values-iscsi.yaml)**
- TrueNAS connection details and ZFS dataset paths (tank/k8s/volumes, tank/k8s/snapshots)
- iSCSI storage class name: `freenas-iscsi-csi`
- TrueNAS host: truenas.lab.thewortmans.org
- ZFS snapshot parent dataset already configured: `detachedSnapshotsDatasetParentName: tank/k8s/snapshots`

**PVC Manifests (pihole/pihole.yaml, nginx-proxy-manager/pvc.yaml)**
- Current PVC definitions use `freenas-iscsi-csi` storage class
- Add annotations and finalizers to these existing PVC definitions
- Retain policy already used in some PVs (media/common.yaml uses `persistentVolumeReclaimPolicy: Retain`)

**Helm Values Pattern (media/sonarr-values.yaml)**
- bjw-s app-template chart pattern for persistence configuration
- Shows how to add annotations via Helm values for PVCs
- `retain: true` already set on config PVC - extend with ArgoCD annotations

**NFS Storage for Synology (media/common.yaml)**
- Synology NAS IP: 192.168.1.230
- Existing NFS mounts demonstrate Synology connectivity
- MinIO will run on same Synology NAS for backup storage

## Out of Scope

- Application-specific backup strategies (database dumps, application-level exports)
- Off-site or cloud backup replication beyond Synology NAS
- Backup encryption at rest (can be added as future enhancement)
- Automated disaster recovery orchestration (manual restore is acceptable)
- Backup monitoring, alerting, or notification systems
- Velero UI or dashboard deployment
- Cross-cluster restore or cluster migration scenarios
- Backup of large media files on NFS (video-pv, music-pv) - these are not critical config data
- MinIO installation itself - user will set up MinIO on Synology manually
- Automated testing or CI/CD for backup validation
