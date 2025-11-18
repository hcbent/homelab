# Tailscale Operator Deployment Checklist

Quick reference for deploying the Tailscale Kubernetes operator.

## Prerequisites

- [ ] Task Group 1 complete (OAuth credentials available)
- [ ] `kubectl` access to cluster verified
- [ ] Nodes healthy: `kubectl get nodes`

## Deployment Steps

### 1. Update ACL Policy

- [ ] Navigate to https://login.tailscale.com/admin/acls
- [ ] Add operator tags to `tagOwners`:
  ```json
  "tag:k8s-operator": ["autogroup:admin"],
  "tag:k8s": ["tag:k8s-operator"]
  ```
- [ ] Save policy and verify no errors

### 2. Create OAuth Credentials

- [ ] Go to https://login.tailscale.com/admin/settings/oauth
- [ ] Click "Generate OAuth client"
- [ ] Configure:
  - Description: `kubernetes-operator`
  - Scopes: ✓ Devices: Write, ✓ Auth Keys: Write
  - Tags: `tag:k8s-operator`
- [ ] Save Client ID and Secret (secret shown once!)

### 3. Deploy Kubernetes Resources

```bash
# Create namespace
kubectl apply -f /Users/bret/git/homelab/k8s/tailscale/namespace.yaml

# Create OAuth secret
/Users/bret/git/homelab/tailscale/scripts/create-operator-oauth-secret.sh

# Deploy RBAC
kubectl apply -f /Users/bret/git/homelab/k8s/tailscale/rbac.yaml

# Deploy operator
kubectl apply -f /Users/bret/git/homelab/k8s/tailscale/operator-deployment.yaml

# Deploy service
kubectl apply -f /Users/bret/git/homelab/k8s/tailscale/service.yaml
```

**Or deploy all at once:**
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/tailscale/
```

### 4. Verification

- [ ] Pod running: `kubectl get pods -n tailscale-system`
- [ ] Logs show success: `kubectl logs -n tailscale-system -l app.kubernetes.io/name=tailscale-operator`
- [ ] Operator in tailnet: https://login.tailscale.com/admin/machines
- [ ] Device tagged: `tag:k8s-operator`
- [ ] Status: Connected

## Quick Commands

```bash
# Watch pod status
kubectl get pods -n tailscale-system -w

# Follow logs
kubectl logs -n tailscale-system -l app.kubernetes.io/name=tailscale-operator -f

# Check deployment
kubectl describe deployment tailscale-operator -n tailscale-system

# Verify secret
kubectl get secret tailscale-operator-oauth -n tailscale-system

# Check service
kubectl get svc -n tailscale-system
```

## Success Criteria

- [x] Namespace `tailscale-system` exists
- [x] Secret `tailscale-operator-oauth` created
- [x] RBAC resources deployed
- [x] Operator pod running (1/1 ready)
- [x] No errors in operator logs
- [x] Operator device visible in Tailscale admin console
- [x] Device shows "Connected" status
- [x] Device has `tag:k8s-operator` tag

## Next: Task Group 3

Once all checks pass, proceed to MagicDNS configuration.
