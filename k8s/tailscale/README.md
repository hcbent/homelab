# Tailscale Kubernetes Operator Deployment

This directory contains Kubernetes manifests for deploying the Tailscale operator to the homelab cluster.

## Overview

The Tailscale Kubernetes operator enables:
- Exposing Kubernetes services via Tailscale mesh network
- Tailscale Ingress for incoming connections
- Tailscale Egress for outgoing connections through the mesh
- Connector functionality for subnet routing
- Funnel support for public service exposure

## Architecture

**Deployment Model:**
- Single operator pod managing all Tailscale connections
- Runs in `tailscale-system` namespace
- Uses OAuth credentials for authentication
- Creates Tailscale auth keys automatically for managed resources

**Security:**
- Non-root container (UID 65532)
- Read-only root filesystem
- Minimal permissions via RBAC
- OAuth credentials stored in Kubernetes secret

**Resource Allocation:**
- CPU Request: 200m
- Memory Request: 512Mi
- CPU Limit: 500m
- Memory Limit: 1Gi

## Files in This Directory

| File | Description |
|------|-------------|
| `namespace.yaml` | Creates `tailscale-system` namespace |
| `rbac.yaml` | ServiceAccount, ClusterRole, ClusterRoleBinding, Role, RoleBinding |
| `operator-deployment.yaml` | Deployment for the Tailscale operator |
| `service.yaml` | NodePort service for operator metrics |

## Prerequisites

Before deploying:

1. **Tailscale Account Setup:**
   - Organization configured
   - ACL policy includes `tag:k8s-operator` and `tag:k8s` definitions
   - OAuth credentials created with required scopes

2. **Required ACL Policy Tags:**
   ```json
   "tagOwners": {
     "tag:k8s-operator": ["autogroup:admin"],
     "tag:k8s": ["tag:k8s-operator"]
   }
   ```

3. **OAuth Credentials:**
   - Created at: https://login.tailscale.com/admin/settings/oauth
   - Scopes: `Devices: Write`, `Auth Keys: Write`
   - Tagged with: `tag:k8s-operator`

## Deployment Instructions

### Step 1: Create Namespace

```bash
kubectl apply -f namespace.yaml
```

### Step 2: Create OAuth Secret

Use the provided script to create the secret with your OAuth credentials:

```bash
/Users/bret/git/homelab/tailscale/scripts/create-operator-oauth-secret.sh
```

This will prompt you for:
- OAuth Client ID
- OAuth Client Secret

### Step 3: Deploy RBAC

```bash
kubectl apply -f rbac.yaml
```

### Step 4: Deploy Operator

```bash
kubectl apply -f operator-deployment.yaml
```

### Step 5: Deploy Service

```bash
kubectl apply -f service.yaml
```

### Step 6: Verify Deployment

```bash
# Check pod status
kubectl get pods -n tailscale-system

# Check operator logs
kubectl logs -n tailscale-system -l app.kubernetes.io/name=tailscale-operator

# Verify in Tailscale admin console
# https://login.tailscale.com/admin/machines
# Look for "tailscale-operator" device
```

## Deploy All at Once

```bash
kubectl apply -f /Users/bret/git/homelab/k8s/tailscale/
```

This will deploy all manifests in order.

## Monitoring

### Check Operator Health

```bash
# Pod status
kubectl get pods -n tailscale-system -w

# Operator logs
kubectl logs -n tailscale-system -l app.kubernetes.io/name=tailscale-operator -f

# Describe deployment
kubectl describe deployment tailscale-operator -n tailscale-system
```

### Health Endpoints

The operator exposes health check endpoints on port 9001:
- `/healthz` - Liveness probe
- `/readyz` - Readiness probe
- `/metrics` - Prometheus metrics

### Access Metrics

```bash
# Port-forward to access metrics locally
kubectl port-forward -n tailscale-system svc/tailscale-operator 9001:9001

# Access metrics at: http://localhost:9001/metrics
```

## Prometheus Integration

The operator exposes Prometheus metrics on port 9001. To integrate with your Prometheus stack, create a ServiceMonitor:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: tailscale-operator
  namespace: tailscale-system
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: tailscale-operator
  endpoints:
  - port: metrics
    interval: 30s
```

## Troubleshooting

### Operator Pod Not Starting

**Check pod events:**
```bash
kubectl describe pod -n tailscale-system -l app.kubernetes.io/name=tailscale-operator
```

**Common issues:**
- Secret not found: Verify `tailscale-operator-oauth` secret exists
- Image pull errors: Check network connectivity
- Permission errors: Verify RBAC was applied

### Authentication Errors

**Error in logs:** "Invalid OAuth credentials"

**Solutions:**
1. Verify OAuth credentials (not just auth keys)
2. Check scopes: Must include "Devices: Write" and "Auth Keys: Write"
3. Verify secret contains correct values:
   ```bash
   kubectl get secret tailscale-operator-oauth -n tailscale-system -o yaml
   ```

### Operator Not Appearing in Tailnet

**Check:**
1. Operator logs for connection errors
2. ACL policy includes `tag:k8s-operator` definition
3. Network connectivity to Tailscale servers
4. OAuth client has correct tags assigned

### Tag Errors

**Error:** "tag:k8s-operator is not defined"

**Solution:** Update ACL policy to include tag definitions (see Prerequisites section)

## Updating the Operator

To update to a new version:

```bash
# Edit operator-deployment.yaml to change image version
# Then apply:
kubectl apply -f operator-deployment.yaml

# Watch rollout
kubectl rollout status deployment/tailscale-operator -n tailscale-system
```

## Uninstalling

To remove the operator:

```bash
# Delete all resources
kubectl delete -f /Users/bret/git/homelab/k8s/tailscale/

# Delete namespace (this will delete everything in it)
kubectl delete namespace tailscale-system
```

**Note:** This will disconnect all Tailscale-managed services.

## Next Steps

After deploying the operator:

1. **Configure MagicDNS** - Enable MagicDNS in Tailscale admin console
2. **Deploy Internal NGINX** - Set up NGINX proxy for *.home.lab routing
3. **Expose Services** - Use operator to expose Kubernetes services via Tailscale

## References

- [Tailscale Kubernetes Operator Documentation](https://tailscale.com/kb/1236/kubernetes-operator)
- [Tailscale ACL Policy Documentation](https://tailscale.com/kb/1018/acls)
- [Tailscale OAuth Clients](https://tailscale.com/kb/1215/oauth-clients)

## Support

For issues specific to this deployment:
- Check operator logs
- Review Tailscale admin console
- Verify prerequisites are met

For Tailscale-specific issues:
- Tailscale documentation: https://tailscale.com/kb
- Tailscale community: https://forum.tailscale.com
