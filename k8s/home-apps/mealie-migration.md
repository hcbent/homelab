# Mealie Migration Guide

## Overview
This document provides step-by-step procedures for migrating Mealie from docker-compose to Kubernetes/ArgoCD.

## Application Details
- **Source:** Docker Compose (`docker/home-apps/docker-compose.yml`)
- **Destination:** Kubernetes namespace `home-apps`
- **Chart:** bjw-s/app-template v3.5.1
- **Port:** NodePort 30925 (maps to container port 9000, external port 9925)
- **Storage:** 10Gi iSCSI PVC (`freenas-iscsi-csi`)

## Prerequisites

### Pre-Migration Checklist
- [ ] Verify Kubernetes cluster is operational
- [ ] Confirm `home-apps` namespace exists
- [ ] Verify `freenas-iscsi-csi` storage class is available
- [ ] Backup existing docker volume data
- [ ] Export Mealie recipes (via web UI or API)
- [ ] Document current docker-compose configuration

### Backup Procedure
```bash
# Export recipes via Mealie web UI
# Navigate to: Settings -> Backups -> Create Backup
# Download backup file to safe location

# Stop Mealie container
cd /path/to/docker/home-apps
docker-compose stop mealie

# Backup volume data
docker run --rm -v home-apps_mealie_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/mealie-data-backup-$(date +%Y%m%d-%H%M%S).tar.gz -C /data .

# Restart container for continued use during migration prep
docker-compose start mealie
```

## Migration Steps

### Step 1: Validate Kubernetes Infrastructure
```bash
# Verify namespace exists
kubectl get namespace home-apps

# Verify storage class
kubectl get storageclass freenas-iscsi-csi

# Verify ArgoCD is ready
kubectl get pods -n argocd
```

### Step 2: Deploy ArgoCD Application
```bash
# Apply the ArgoCD Application manifest
kubectl apply -f /Users/bret/git/homelab/k8s/mealie-app.yaml

# Monitor sync status
kubectl get application -n argocd mealie

# Wait for application to sync
argocd app wait mealie --health
```

### Step 3: Verify Deployment
```bash
# Check pod status
kubectl get pods -n home-apps -l app.kubernetes.io/name=mealie

# Check service
kubectl get svc -n home-apps -l app.kubernetes.io/name=mealie

# Check PVC
kubectl get pvc -n home-apps | grep mealie

# Run automated tests
/Users/bret/git/homelab/k8s/home-apps/mealie-tests.sh
```

### Step 4: Migrate Data
```bash
# Get pod name
POD_NAME=$(kubectl get pods -n home-apps -l app.kubernetes.io/name=mealie -o jsonpath='{.items[0].metadata.name}')

# Copy backup to pod
kubectl cp mealie-data-backup-*.tar.gz home-apps/$POD_NAME:/tmp/

# Extract data in pod
kubectl exec -n home-apps $POD_NAME -- sh -c 'cd /app/data && tar xzf /tmp/mealie-data-backup-*.tar.gz'

# Restart pod to pick up new data
kubectl delete pod -n home-apps $POD_NAME
kubectl wait --for=condition=ready pod -n home-apps -l app.kubernetes.io/name=mealie --timeout=120s
```

### Step 5: Cutover
```bash
# Stop docker-compose service
cd /path/to/docker/home-apps
docker-compose stop mealie

# Verify Kubernetes service is accessible
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
curl http://$NODE_IP:30925/

# Update NGINX Proxy Manager or router to point to new NodePort
# (Out of scope - manual configuration)
```

## Validation Criteria

### Application Health
- [ ] Pod is running and ready
- [ ] NodePort service accessible on port 30925
- [ ] Web UI loads successfully
- [ ] Recipes visible (if migrated)
- [ ] Can create/modify recipes
- [ ] Search functionality works
- [ ] Image uploads work

### Performance
- [ ] Response time is acceptable (< 2 seconds for page load)
- [ ] No errors in pod logs
- [ ] Recipe search is responsive

### Persistence
- [ ] Data survives pod restart
- [ ] PVC remains bound after pod restart
- [ ] Uploaded images persist

## Post-Migration

### Monitoring
```bash
# Check pod logs
kubectl logs -n home-apps -l app.kubernetes.io/name=mealie -f

# Check resource usage
kubectl top pod -n home-apps -l app.kubernetes.io/name=mealie

# Monitor ArgoCD sync status
kubectl get application -n argocd mealie -w
```

### Validation Period
- Run in production for minimum 7 days
- Monitor for stability and performance
- Verify data integrity
- Test recipe imports/exports
- Document any issues

## Rollback Procedure

### When to Rollback
- Persistent application failures
- Data corruption or loss
- Critical features unavailable (search, image uploads, etc.)
- Performance degradation

### Rollback Steps
```bash
# Scale Kubernetes deployment to 0
kubectl scale deployment -n home-apps -l app.kubernetes.io/name=mealie --replicas=0

# Restore docker volume from backup (if needed)
cd /path/to/docker/home-apps
docker run --rm -v home-apps_mealie_data:/data -v $(pwd):/backup \
  alpine sh -c 'cd /data && tar xzf /backup/mealie-data-backup-*.tar.gz'

# Restart docker-compose service
docker-compose start mealie

# Verify service is accessible
curl http://localhost:9925/

# Update NGINX Proxy Manager or router to point back to docker host
# (Out of scope - manual configuration)
```

### Post-Rollback
- Document rollback reason
- Investigate root cause
- Fix issues before re-attempting migration

## Troubleshooting

### Pod Not Starting
```bash
# Check pod events
kubectl describe pod -n home-apps -l app.kubernetes.io/name=mealie

# Check logs
kubectl logs -n home-apps -l app.kubernetes.io/name=mealie

# Common issues:
# - PVC binding failure: Check storage class availability
# - Image pull errors: Verify image name and network connectivity
# - Permission errors: Check securityContext settings (PUID/PGID)
```

### PVC Binding Issues
```bash
# Check PVC status
kubectl describe pvc -n home-apps | grep mealie

# Check CSI driver
kubectl get pods -n democratic-csi | grep iscsi

# Verify storage class
kubectl get storageclass freenas-iscsi-csi -o yaml
```

### Service Not Accessible
```bash
# Check service endpoints
kubectl get endpoints -n home-apps -l app.kubernetes.io/name=mealie

# Verify NodePort
kubectl get svc -n home-apps -l app.kubernetes.io/name=mealie

# Test from another pod
kubectl run -it --rm debug --image=alpine --restart=Never -- sh
  apk add curl
  curl http://mealie-service.home-apps.svc.cluster.local:9000/
```

### Image Upload Issues
```bash
# Check PVC mount
kubectl exec -n home-apps -l app.kubernetes.io/name=mealie -- df -h /app/data

# Check permissions
kubectl exec -n home-apps -l app.kubernetes.io/name=mealie -- ls -la /app/data

# Verify PUID/PGID
kubectl exec -n home-apps -l app.kubernetes.io/name=mealie -- id
```

## Notes
- Docker-compose file preserved at `docker/home-apps/docker-compose.yml`
- Original volume data preserved until migration validated
- NodePort 30925 chosen to match docker-compose external port
- No Vault secrets required for Mealie
- PUID/PGID set to 1000:1000 for file ownership consistency
- Application listens on port 9000 internally, NodePort exposes as 30925
