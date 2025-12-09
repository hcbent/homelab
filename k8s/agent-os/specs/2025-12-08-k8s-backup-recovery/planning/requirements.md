# Spec Requirements: Kubernetes Backup and Recovery

## Initial Description

We need a way to back up k8s pods and configuration so that recovery is always possible.

This is for a homelab Kubernetes cluster. The user recently lost configuration data for Sonarr and Radarr when PVCs were accidentally deleted, so backup and recovery is a priority.

**Context:**
- Environment: Homelab Kubernetes cluster
- Trigger: Recent data loss incident involving Sonarr and Radarr PVCs
- Problem: PVCs were accidentally deleted, causing configuration data loss
- Need: Comprehensive backup and recovery solution for pods and configuration

## Requirements Discussion

### First Round Questions

**Q1:** What is the backup scope - just PVC data, or also cluster state (etcd)?
**Answer:** Both PVC data AND cluster state (etcd). Everything. Need to recover quickly from disasters and human error.

**Q2:** Which applications need to be backed up?
**Answer:** All apps with PVCs - no exclusions to start. Includes: Sonarr, Radarr, Plex, qBittorrent, Jackett, Pi-hole, Mealie, and any others.

**Q3:** What is the backup storage destination?
**Answer:** Synology NAS - create a new share with MinIO for S3-compatible storage.

**Q4:** Preference between ZFS snapshots vs application-level backup (Velero)?
**Answer:** Velero confirmed as primary tool. Additionally, trigger ZFS snapshots on TrueNAS as a secondary protection layer (belt + suspenders approach).

**Q5:** What backup schedule/frequency is required?
**Answer:** Daily backups. 24 hours of data loss is acceptable.

**Q6:** Should there be different backup tiers for different applications?
**Answer:** Single unified approach for all apps.

**Q7:** What recovery types are needed?
**Answer:** Yes to both granular (single app PVC) AND full disaster recovery.

**Q8:** Should safeguards against accidental deletion be implemented?
**Answer:** Yes, implement Prune=false annotations and finalizers to prevent accidental deletion.

**Q9:** Are there any exclusions or out-of-scope items?
**Answer:** Not specified - assume no exclusions.

### Existing Code to Reference

**Infrastructure Context Identified:**
- ArgoCD GitOps deployment model
- TrueNAS with democratic-csi for iSCSI storage (primary storage backend)
- Synology NAS for backup destination (will run MinIO)
- Recent incident: ArgoCD pruning deleted Sonarr/Radarr PVCs, losing all configuration

No specific existing backup code or patterns identified for reference.

### Follow-up Questions

**Follow-up 1:** What backup tool do you prefer - Velero (industry standard) or another solution?
**Answer:** Velero - confirmed.

**Follow-up 2:** For Synology NAS storage, should we use an existing share or create a new one? NFS vs S3-compatible (MinIO)?
**Answer:** Create a new share. User will set up MinIO on Synology for S3-compatible storage.

**Follow-up 3:** What retention policy should be used?
**Answer:** 7 daily + 4 weekly backups (approximately 1 month of coverage).

**Follow-up 4:** For TrueNAS ZFS integration, should we: (A) trigger ZFS snapshots as additional protection, or (B) rely solely on Velero?
**Answer:** Option A - trigger ZFS snapshots as additional protection layer. Belt + suspenders approach with Synology/MinIO as off-site copy.

## Visual Assets

### Files Provided:
No visual assets provided.

### Visual Insights:
N/A

## Requirements Summary

### Functional Requirements
- Comprehensive backup of all PVC data across the cluster using Velero
- Backup of cluster state (etcd) for disaster recovery
- Daily backup schedule (RPO: 24 hours)
- Storage of backups to MinIO on Synology NAS (S3-compatible)
- 7 daily + 4 weekly backup retention policy
- Granular recovery capability (restore single application/namespace)
- Full disaster recovery capability (restore entire cluster)
- ZFS snapshots on TrueNAS as secondary/fast local recovery option
- Protection against accidental deletion via ArgoCD pruning

### Reusability Opportunities
- Existing democratic-csi configuration for understanding storage topology
- ArgoCD patterns for GitOps deployment of Velero
- Synology NAS available for MinIO deployment

### Scope Boundaries

**In Scope:**
- Velero installation and configuration via ArgoCD
- MinIO setup on Synology NAS (or documentation for user to set up)
- Backup schedules for all namespaces with PVCs
- Restic/Kopia integration for PVC data backup
- S3 backup location configuration pointing to Synology MinIO
- Etcd backup strategy for cluster state
- ZFS snapshot triggering on TrueNAS as secondary protection
- ArgoCD annotations to prevent accidental PVC deletion (Prune=false)
- Finalizers on PVCs to prevent immediate deletion
- Retention policy: 7 daily + 4 weekly backups
- Documentation for recovery procedures
- Testing/validation of backup and restore workflows

**Out of Scope:**
- Application-specific backup strategies (database dumps, etc.)
- Off-site/cloud backup replication beyond Synology
- Backup encryption (can be added later)
- Automated disaster recovery (manual restore is acceptable)
- Backup monitoring/alerting (can be added as enhancement)

### Technical Considerations
- **Primary Backup Tool:** Velero with Restic/Kopia for file-level PVC backup
- **Storage Backend:** MinIO on Synology NAS (S3-compatible) - user will set up MinIO
- **Secondary Protection:** ZFS snapshots on TrueNAS for fast local recovery
- **GitOps Deployment:** Velero should be deployed via ArgoCD for consistency
- **Retention Policy:** 7 daily + 4 weekly backups (~1 month coverage)
- **ArgoCD Protection:** Add `argocd.argoproj.io/sync-options: Prune=false` to PVC resources
- **Finalizer Protection:** Add finalizers to PVCs to require explicit removal before deletion
- **Etcd Backup:** Consider k3s/kubeadm built-in etcd snapshot capabilities alongside Velero
- **Applications to Back Up:** Sonarr, Radarr, Plex, qBittorrent, Jackett, Pi-hole, Mealie, and all other apps with PVCs
