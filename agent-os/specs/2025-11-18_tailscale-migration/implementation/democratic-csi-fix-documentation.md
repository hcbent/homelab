# Democratic-CSI Storage Fix Documentation

## Issue Summary

The democratic-csi iSCSI driver was returning 404 errors when attempting to provision new volumes, causing PVCs to remain in Pending state.

### Root Cause

TrueNAS SCALE 25.04 removed the `/api/v2.0/iscsi/targetgroup` API endpoint that the democratic-csi driver was using. The driver with the `latest` image tag did not have support for this API change.

### TrueNAS Version
- **TrueNAS SCALE Version:** 25.04.2.3

### Error Message
```
error getting iscsi configuration - code: 404 body: "404: Not Found"
```

## Solution

Updated the democratic-csi deployment to use the `next` image tag instead of `latest`. The `next` image contains commits from April 2025 that add TrueNAS SCALE 25.04+ support.

### Key Changes

1. **Image Tag Update**: Changed from `democraticcsi/democratic-csi:latest` to `democraticcsi/democratic-csi:next`

2. **Values File Created**: `/Users/bret/git/homelab/k8s/democratic-csi/values-iscsi.yaml`
   - Includes full driver configuration inline
   - Uses API key authentication
   - Configured for TrueNAS at truenas.lab.thewortmans.org

3. **StorageClass Configuration**:
   - Name: freenas-iscsi-csi
   - fsType: ext4
   - ReclaimPolicy: Delete
   - VolumeBindingMode: Immediate
   - AllowVolumeExpansion: true

### Democratic-CSI Version Information
- Package Version: 1.9.0
- CSI Version: 1.5.0
- Node Version: v20.19.0

## Configuration Details

### TrueNAS Connection
- HTTP API: http://truenas.lab.thewortmans.org:80
- SSH: truenas.lab.thewortmans.org:22
- iSCSI Portal: truenas.lab.thewortmans.org:3260
- API Version: 2

### ZFS Configuration
- Dataset Parent: tank/k8s/volumes
- Snapshots Parent: tank/k8s/snapshots
- Permissions Mode: 0770

### iSCSI Configuration
- Target Group Portal Group: 2
- Target Group Initiator Group: 1
- Auth Type: None
- Extent RPM: SSD
- Extent Blocksize: 512

## Verification Steps

1. All pods running in democratic-csi namespace:
   - democratic-csi-iscsi-controller (6/6 containers)
   - democratic-csi-iscsi-node (4/4 containers on each node)

2. ArgoCD Application Status:
   - Sync: Synced
   - Health: Healthy

3. Test PVC provisioning:
   - Create test PVC with freenas-iscsi-csi storage class
   - Verify PVC becomes Bound
   - Verify volume created in TrueNAS
   - Clean up test resources

## Affected Resources

### Successfully Provisioned PVCs
- nginx-proxy-manager-data (1Gi) - Bound
- nginx-proxy-manager-letsencrypt (1Gi) - Bound

### Pre-existing PVCs (unaffected by fix)
- actualbudget-data
- mealie-data
- mealie-postgres
- jackett-config
- jackett-downloads
- qbittorrent-config
- radarr-config
- sonarr-config
- unpackerr-config

## Future Considerations

1. **Image Versioning**: When democratic-csi releases a stable version with TrueNAS SCALE 25.04+ support, consider pinning to that specific version instead of `next`.

2. **Vault Integration**: The current values file contains credentials inline. Consider migrating to External Secrets Operator to pull credentials from Vault for better security.

3. **NFS Driver**: The NFS driver (democratic-csi-nfs) also needs a values file created at `/Users/bret/git/homelab/k8s/democratic-csi/values-nfs.yaml` if NFS storage provisioning is needed.

## Git Commits

1. **694c225**: "Fix democratic-csi for TrueNAS SCALE API compatibility"
   - Initial values file with existingConfigSecret reference

2. **8ab307b**: "Include full driver config in democratic-csi values"
   - Updated to include complete driver configuration inline

## References

- GitHub Issue #509: TrueNAS REST API deprecation in 25.04
- democratic-csi GitHub: https://github.com/democratic-csi/democratic-csi
- Commit: "support TN 25.04, env vars in config, improved Dockerfiles" (Apr 5, 2025)
