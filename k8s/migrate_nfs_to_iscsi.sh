#!/bin/bash

# Script to migrate Kubernetes PVCs from NFS to TrueNAS iSCSI

# Configuration variables
NAMESPACE="default" 
# NAMESPACE="vault"
# NAMESPACE="elastic-stack"
STORAGE_CLASS_NAME="truenas-iscsi"
TRUE_NAS_DATASET="tank/k8s/iscsi"
NFS_PVC_LABEL="storage=nfs"
TEMP_POD_PREFIX="data-migration-pod"
NEW_PVC_PREFIX="iscsi-pvc"
KUBECTL="kubectl"
JQ="jq"
TIMEOUT_SECONDS=600

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Function to log messages
log() {
    echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to check if a command exists
check_command() {
    if ! command -v "$1" &> /dev/null; then
        log "${RED}Error: $1 is required but not installed.${NC}"
        exit 1
    fi
}

# Check prerequisites
check_command "$KUBECTL"
check_command "$JQ"

# Step 1: Create StorageClass for TrueNAS iSCSI
log "Creating StorageClass for TrueNAS iSCSI..."
cat <<EOF | $KUBECTL apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: $STORAGE_CLASS_NAME
provisioner: org.democratic-csi.iscsi
parameters:
  fsType: ext4
  datasetParentName: $TRUE_NAS_DATASET
reclaimPolicy: Delete
volumeBindingMode: Immediate
allowVolumeExpansion: true
EOF

if [ $? -ne 0 ]; then
    log "${RED}Error: Failed to create StorageClass $STORAGE_CLASS_NAME.${NC}"
    exit 1
fi
log "${GREEN}StorageClass $STORAGE_CLASS_NAME created successfully.${NC}"

# Step 2: Get list of NFS PVCs to migrate
log "Fetching NFS PVCs with label $NFS_PVC_LABEL..."
PVC_LIST=$($KUBECTL get pvc -n $NAMESPACE -l $NFS_PVC_LABEL -o json | $JQ -r '.items[].metadata.name')
if [ -z "$PVC_LIST" ]; then
    log "${RED}Error: No PVCs found with label $NFS_PVC_LABEL.${NC}"
    exit 1
fi

# Step 3: Migrate each PVC
for OLD_PVC in $PVC_LIST; do
    log "Processing PVC: $OLD_PVC"

    # Get storage request size
    STORAGE_SIZE=$($KUBECTL get pvc $OLD_PVC -n $NAMESPACE -o json | $JQ -r '.spec.resources.requests.storage')
    if [ -z "$STORAGE_SIZE" ]; then
        log "${RED}Error: Could not determine storage size for $OLD_PVC.${NC}"
        continue
    fi

    # Create new iSCSI PVC
    NEW_PVC_NAME="${NEW_PVC_PREFIX}-${OLD_PVC}"
    log "Creating new iSCSI PVC: $NEW_PVC_NAME"
    cat <<EOF | $KUBECTL apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $NEW_PVC_NAME
  namespace: $NAMESPACE
spec:
  storageClassName: $STORAGE_CLASS_NAME
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: $STORAGE_SIZE
EOF

    if [ $? -ne 0 ]; then
        log "${RED}Error: Failed to create PVC $NEW_PVC_NAME.${NC}"
        continue
    fi

    # Wait for new PVC to be bound
    log "Waiting for $NEW_PVC_NAME to be bound..."
    $KUBECTL wait --for=condition=Bound pvc/$NEW_PVC_NAME -n $NAMESPACE --timeout=${TIMEOUT_SECONDS}s
    if [ $? -ne 0 ]; then
        log "${RED}Error: PVC $NEW_PVC_NAME failed to bind.${NC}"
        continue
    fi
    log "${GREEN}PVC $NEW_PVC_NAME bound successfully.${NC}"

    # Step 4: Create migration pod to copy data
    MIGRATION_POD="${TEMP_POD_PREFIX}-${OLD_PVC}"
    log "Creating migration pod: $MIGRATION_POD"
    cat <<EOF | $KUBECTL apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: $MIGRATION_POD
  namespace: $NAMESPACE
spec:
  containers:
  - name: migration
    image: busybox
    command: ["/bin/sh", "-c", "cp -r /nfs/* /iscsi/ && echo 'Copy complete' && sleep 3600"]
    volumeMounts:
    - name: nfs-volume
      mountPath: /nfs
    - name: iscsi-volume
      mountPath: /iscsi
  volumes:
  - name: nfs-volume
    persistentVolumeClaim:
      claimName: $OLD_PVC
  - name: iscsi-volume
    persistentVolumeClaim:
      claimName: $NEW_PVC_NAME
EOF

    if [ $? -ne 0 ]; then
        log "${RED}Error: Failed to create migration pod $MIGRATION_POD.${NC}"
        continue
    fi

    # Wait for data copy to completeArrays
    log "Waiting for data migration to complete in pod $MIGRATION_POD..."
    $KUBECTL wait --for=condition=Ready pod/$MIGRATION_POD -n $NAMESPACE --timeout=${TIMEOUT_SECONDS}s
    if [ $? -ne 0 ]; then
        log "${RED}Error: Migration pod $MIGRATION_POD failed to start.${NC}"
        continue
    fi

    # Check logs for completion
    until $KUBECTL logs $MIGRATION_POD -n $NAMESPACE | grep -q "Copy complete"; do
        sleep 5
        log "Waiting for data copy to complete..."
    done
    log "${GREEN}Data migration for $OLD_PVC to $NEW_PVC_NAME completed.${NC}"

    # Clean up migration pod
    log "Cleaning up migration pod $MIGRATION_POD..."
    $KUBECTL delete pod $MIGRATION_POD -n $NAMESPACE --wait
    if [ $? -ne 0 ]; then
        log "${RED}Error: Failed to delete migration pod $MIGRATION_POD.${NC}"
    else
        log "${GREEN}Migration pod $MIGRATION_POD deleted.${NC}"
    fi
done

# Step 5: Output instructions for manual steps
log "${GREEN}Migration complete! Next steps:${NC}"
log "1. Update your workloads to use the new iSCSI PVCs (e.g., $NEW_PVC_PREFIX-*)."
log "2. Verify data integrity in the new PVCs."
log "3. Delete old NFS PVCs after validation with: $KUBECTL delete pvc -l $NFS_PVC_LABEL -n $NAMESPACE"
log "4. Optionally, remove the old NFS StorageClass if no longer needed."

exit 0
