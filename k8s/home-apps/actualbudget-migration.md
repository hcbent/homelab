# Actualbudget Migration Guide

## Overview
This document provides step-by-step procedures for migrating Actualbudget from docker-compose to Kubernetes/ArgoCD.

## Application Details
- **Source:** Docker Compose (`docker/home-apps/docker-compose.yml`)
- **Destination:** Kubernetes namespace `home-apps`
- **Chart:** community-charts/actualbudget v1.7.2
- **Port:** NodePort 30006 (maps to container port 5006)
- **Storage:** 5Gi iSCSI PVC (`freenas-iscsi-csi`)

## Prerequisites

### Pre-Migration Checklist
- [ ] Verify Kubernetes cluster is operational
- [ ] Confirm `home-apps` namespace exists
- [ ] Verify `freenas-iscsi-csi` storage class is available
- [ ] Backup existing docker volume data
- [ ] Export Actualbudget data (if applicable)
- [ ] Document current docker-compose configuration

### Backup Procedure
```bash
# Stop Actualbudget container
cd /path/to/docker/home-apps
docker-compose stop actualbudget

# Backup volume data
docker run --rm -v home-apps_actualbudget_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/actualbudget-data-backup-$(date +%Y%m%d-%H%M%S).tar.gz -C /data .

# Restart container for continued use during migration prep
docker-compose start actualbudget
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
kubectl apply -f /Users/bret/git/homelab/k8s/actualbudget-app.yaml

# Monitor sync status
kubectl get application -n argocd actualbudget

# Wait for application to sync
argocd app wait actualbudget --health
```

### Step 3: Verify Deployment
```bash
# Check pod status
kubectl get pods -n home-apps -l app.kubernetes.io/name=actualbudget

# Check service
kubectl get svc -n home-apps -l app.kubernetes.io/name=actualbudget

# Check PVC
kubectl get pvc -n home-apps

# Run automated tests
/Users/bret/git/homelab/k8s/home-apps/actualbudget-tests.sh
```

### Step 4: Migrate Data (Optional - if data exists)
```bash
# Get pod name
POD_NAME=$(kubectl get pods -n home-apps -l app.kubernetes.io/name=actualbudget -o jsonpath='{.items[0].metadata.name}')

# Copy backup to pod
kubectl cp actualbudget-data-backup-*.tar.gz home-apps/$POD_NAME:/tmp/

# Extract data in pod
kubectl exec -n home-apps $POD_NAME -- sh -c 'cd /data && tar xzf /tmp/actualbudget-data-backup-*.tar.gz'

# Restart pod to pick up new data
kubectl delete pod -n home-apps $POD_NAME
kubectl wait --for=condition=ready pod -n home-apps -l app.kubernetes.io/name=actualbudget --timeout=120s
```

### Step 5: Cutover
```bash
# Stop docker-compose service
cd /path/to/docker/home-apps
docker-compose stop actualbudget

# Verify Kubernetes service is accessible
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
curl http://$NODE_IP:30006/

# Update NGINX Proxy Manager or router to point to new NodePort
# (Out of scope - manual configuration)
```

## Validation Criteria

### Application Health
- [ ] Pod is running and ready
- [ ] NodePort service accessible on port 30006
- [ ] Web UI loads successfully
- [ ] Data is visible (if migrated)
- [ ] Can create/modify budget data

### Performance
- [ ] Response time is acceptable (< 2 seconds for page load)
- [ ] No errors in pod logs

### Persistence
- [ ] Data survives pod restart
- [ ] PVC remains bound after pod restart

## Post-Migration

### Monitoring
```bash
# Check pod logs
kubectl logs -n home-apps -l app.kubernetes.io/name=actualbudget -f

# Check resource usage
kubectl top pod -n home-apps -l app.kubernetes.io/name=actualbudget

# Monitor ArgoCD sync status
kubectl get application -n argocd actualbudget -w
```

### Validation Period
- Run in production for minimum 7 days
- Monitor for stability and performance
- Verify data integrity
- Document any issues

## Rollback Procedure

### When to Rollback
- Persistent application failures
- Data corruption or loss
- Critical features unavailable
- Performance degradation

### Rollback Steps
```bash
# Scale Kubernetes deployment to 0
kubectl scale deployment -n home-apps -l app.kubernetes.io/name=actualbudget --replicas=0

# Restore docker volume from backup (if needed)
cd /path/to/docker/home-apps
docker run --rm -v home-apps_actualbudget_data:/data -v $(pwd):/backup \
  alpine sh -c 'cd /data && tar xzf /backup/actualbudget-data-backup-*.tar.gz'

# Restart docker-compose service
docker-compose start actualbudget

# Verify service is accessible
curl http://localhost:5006/

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
kubectl describe pod -n home-apps -l app.kubernetes.io/name=actualbudget

# Check logs
kubectl logs -n home-apps -l app.kubernetes.io/name=actualbudget

# Common issues:
# - PVC binding failure: Check storage class availability
# - Image pull errors: Verify image name and network connectivity
# - Permission errors: Check securityContext settings
```

### PVC Binding Issues
```bash
# Check PVC status
kubectl describe pvc -n home-apps

# Check CSI driver
kubectl get pods -n democratic-csi | grep iscsi

# Verify storage class
kubectl get storageclass freenas-iscsi-csi -o yaml
```

### Service Not Accessible
```bash
# Check service endpoints
kubectl get endpoints -n home-apps

# Verify NodePort
kubectl get svc -n home-apps -l app.kubernetes.io/name=actualbudget

# Test from another pod
kubectl run -it --rm debug --image=alpine --restart=Never -- sh
  apk add curl
  curl http://actualbudget-service.home-apps.svc.cluster.local:5006/
```

## Notes
- Docker-compose file preserved at `docker/home-apps/docker-compose.yml`
- Original volume data preserved until migration validated
- NodePort 30006 chosen to avoid conflicts with existing services
- No Vault secrets required for Actualbudget (no sensitive configuration)
