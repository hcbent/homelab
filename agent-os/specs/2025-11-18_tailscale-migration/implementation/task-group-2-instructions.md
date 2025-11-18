# Task Group 2: Tailscale Kubernetes Operator Deployment - Implementation Instructions

**Status:** Ready for execution
**Dependencies:** Task Group 1 must be complete
**Estimated Time:** 30-45 minutes

## Overview

This task group deploys the Tailscale Kubernetes operator to your 3-node cluster (km01, km02, km03). The operator will manage Tailscale connections for your Kubernetes workloads and enable your cluster nodes to join the Tailscale mesh network.

## Prerequisites Checklist

Before starting, verify:

- [ ] Task Group 1 is complete (OAuth credentials generated and ACL policy applied)
- [ ] You have access to Tailscale admin console: https://login.tailscale.com/admin
- [ ] You have `kubectl` access to your Kubernetes cluster
- [ ] Nodes km01, km02, km03 are running and healthy: `kubectl get nodes`

## Important Concepts

**OAuth Credentials vs. Auth Keys:**
- The Tailscale **operator** uses OAuth credentials (client ID + secret)
- The operator then generates auth keys automatically for managed resources
- You created OAuth credentials in Task Group 1, not just an auth key

**What the operator does:**
- Manages Tailscale connections for Kubernetes services
- Enables Ingress, Egress, and Connector functionality
- Automatically handles device registration in your tailnet
- Can expose services via Tailscale Funnel (for public access)

## Step 1: Update Tailscale ACL Policy (CRITICAL)

The operator requires specific tags to be defined in your ACL policy. You need to update the policy you created in Task Group 1.

### 1.1 Navigate to ACL Policy

1. Go to: https://login.tailscale.com/admin/acls
2. You should see the permissive policy you created in Task Group 1

### 1.2 Add Required Tag Definitions

Find the `"tagOwners"` section and update it to include the operator tags:

```json
{
  "tagOwners": {
    "tag:kubernetes": [],
    "tag:homelab": [],
    "tag:k8s-operator": [],
    "tag:k8s": ["tag:k8s-operator"]
  },
  // ... rest of your ACL policy
}
```

**Key points:**
- `tag:k8s-operator`: Tag for the operator itself
- `tag:k8s`: Tag that the operator assigns to managed services
- The operator (`tag:k8s-operator`) is the owner of `tag:k8s`

### 1.3 Save and Test

1. Click "Save" in the Tailscale admin console
2. The policy will be validated automatically
3. If there are errors, review the syntax and fix them

## Step 2: Create OAuth Credentials for the Operator

The operator needs its own OAuth credentials (separate from what you may have created in Task Group 1 for node auth).

### 2.1 Navigate to OAuth Settings

1. Go to: https://login.tailscale.com/admin/settings/oauth
2. Click "Generate OAuth client"

### 2.2 Configure OAuth Client

**Settings:**
- **Description:** `kubernetes-operator` (or similar descriptive name)
- **Scopes:**
  - ✓ `Devices: Read/Write` (or `Devices Core: Write`)
  - ✓ `Auth Keys: Write`
- **Tags:** Add `tag:k8s-operator`

### 2.3 Save Credentials

After clicking "Generate", you'll see:
- **OAuth Client ID:** `tsoc-xxx...` (starts with `tsoc-`)
- **OAuth Client Secret:** Long alphanumeric string (shown once)

**IMPORTANT:** Copy both values immediately. The secret is only shown once.

Save them temporarily in a secure location. You'll use them in the next step.

## Step 3: Create Kubernetes Namespace

```bash
kubectl apply -f /Users/bret/git/homelab/k8s/tailscale/namespace.yaml
```

**Verify:**
```bash
kubectl get namespace tailscale-system
```

You should see the namespace listed.

## Step 4: Create Kubernetes Secret with OAuth Credentials

Run the provided script to create the secret:

```bash
/Users/bret/git/homelab/tailscale/scripts/create-operator-oauth-secret.sh
```

The script will prompt you for:
1. OAuth Client ID (from Step 2)
2. OAuth Client Secret (from Step 2)

**Expected output:**
```
SUCCESS: Kubernetes secret 'tailscale-operator-oauth' created in namespace 'tailscale-system'
```

**Verify the secret exists:**
```bash
kubectl get secret tailscale-operator-oauth -n tailscale-system
```

**Security note:** The secret is stored securely in Kubernetes. Do not commit the OAuth credentials to git.

## Step 5: Deploy RBAC Resources

The operator needs permissions to manage Kubernetes resources.

```bash
kubectl apply -f /Users/bret/git/homelab/k8s/tailscale/rbac.yaml
```

**Verify:**
```bash
kubectl get serviceaccount tailscale-operator -n tailscale-system
kubectl get clusterrole tailscale-operator
kubectl get clusterrolebinding tailscale-operator
```

All three should show as created.

## Step 6: Deploy the Tailscale Operator

```bash
kubectl apply -f /Users/bret/git/homelab/k8s/tailscale/operator-deployment.yaml
```

**Verify deployment:**
```bash
kubectl get deployment -n tailscale-system
kubectl get pods -n tailscale-system
```

**Expected output:**
```
NAME                   READY   STATUS    RESTARTS   AGE
tailscale-operator-*   1/1     Running   0          30s
```

## Step 7: Deploy NodePort Service

```bash
kubectl apply -f /Users/bret/git/homelab/k8s/tailscale/service.yaml
```

**Verify:**
```bash
kubectl get svc -n tailscale-system
```

## Step 8: Monitor Operator Startup

Watch the operator logs to ensure it starts successfully:

```bash
kubectl logs -n tailscale-system -l app.kubernetes.io/name=tailscale-operator -f
```

**What to look for:**
- ✓ "Successfully authenticated with Tailscale"
- ✓ "Operator started"
- ✓ No error messages about OAuth credentials
- ✗ Any errors about authentication or permissions

**Let it run for 1-2 minutes**, then press Ctrl+C to exit.

## Step 9: Verify Operator in Tailscale Admin Console

1. Go to: https://login.tailscale.com/admin/machines
2. Look for a device named `tailscale-operator`
3. Verify it shows as "Connected"
4. Check that it has the tag `tag:k8s-operator`

**If you don't see it:**
- Check operator logs for errors
- Verify OAuth credentials are correct
- Ensure ACL policy includes the tag definitions

## Step 10: Check Operator Health

```bash
# Check pod status
kubectl get pods -n tailscale-system

# Check operator logs for any errors
kubectl logs -n tailscale-system -l app.kubernetes.io/name=tailscale-operator --tail=50

# Describe the deployment
kubectl describe deployment tailscale-operator -n tailscale-system
```

**Health indicators:**
- Pod status: `Running`
- Ready: `1/1`
- Restarts: `0` (or very low number)
- No error messages in logs

## Step 11: Verify Kubernetes Nodes DO NOT Appear in Tailnet Yet

At this point, only the **operator** should appear in your tailnet, not the individual Kubernetes nodes (km01, km02, km03).

**Why?** The operator doesn't automatically add nodes to the tailnet. You'll configure that in the next phase when you deploy services that need Tailscale connectivity.

**Verify in admin console:**
1. Go to: https://login.tailscale.com/admin/machines
2. You should see: `tailscale-operator` (connected)
3. You should NOT see: km01, km02, km03 (they'll be added later when needed)

## Troubleshooting

### Operator Pod Not Starting

**Check pod events:**
```bash
kubectl describe pod -n tailscale-system -l app.kubernetes.io/name=tailscale-operator
```

**Common issues:**
- Image pull errors: Check network connectivity
- Secret not found: Verify secret was created in Step 4
- Permission errors: Verify RBAC was applied in Step 5

### Authentication Errors in Logs

**Error:** "Invalid OAuth credentials"

**Solution:**
1. Verify you created OAuth credentials (not just an auth key)
2. Check scopes include "Devices Core: Write" and "Auth Keys: Write"
3. Verify secret was created correctly:
   ```bash
   kubectl get secret tailscale-operator-oauth -n tailscale-system -o yaml
   ```

### Operator Not Appearing in Tailnet

**Error:** Operator pod is running but doesn't show in admin console

**Solution:**
1. Check operator logs for connection errors
2. Verify ACL policy includes `tag:k8s-operator` definition
3. Check network connectivity from cluster to Tailscale servers
4. Verify OAuth client has correct tags assigned

### Tag Not Defined Error

**Error:** "tag:k8s-operator is not defined in ACL policy"

**Solution:**
1. Go back to Step 1 and add the tag definitions
2. The ACL policy MUST include both `tag:k8s-operator` and `tag:k8s`

## Verification Checklist

Before proceeding to Task Group 3, verify:

- [ ] Namespace `tailscale-system` exists
- [ ] Secret `tailscale-operator-oauth` created with OAuth credentials
- [ ] RBAC resources deployed (ServiceAccount, ClusterRole, ClusterRoleBinding)
- [ ] Operator deployment running (1/1 pods ready)
- [ ] NodePort service created
- [ ] Operator logs show successful startup (no errors)
- [ ] Operator device appears in Tailscale admin console
- [ ] Operator device is tagged with `tag:k8s-operator`
- [ ] Operator device shows as "Connected"

## Success Criteria

✓ Tailscale operator running in Kubernetes
✓ Operator successfully authenticated with Tailscale
✓ Operator device visible and connected in tailnet
✓ No error messages in operator logs
✓ Health probes passing (Ready: 1/1)

## Next Steps

Once all verification steps pass, you're ready for **Task Group 3: MagicDNS Configuration**.

In the next phase, you'll:
1. Enable MagicDNS globally in Tailscale
2. Configure the `*.home.lab` internal domain
3. Test DNS resolution from Tailscale-connected devices

## Files Created in This Task Group

**Kubernetes Manifests:**
- `/Users/bret/git/homelab/k8s/tailscale/namespace.yaml` - Namespace definition
- `/Users/bret/git/homelab/k8s/tailscale/rbac.yaml` - RBAC resources
- `/Users/bret/git/homelab/k8s/tailscale/operator-deployment.yaml` - Operator deployment
- `/Users/bret/git/homelab/k8s/tailscale/service.yaml` - NodePort service

**Helper Scripts:**
- `/Users/bret/git/homelab/tailscale/scripts/create-operator-oauth-secret.sh` - OAuth secret creation

**Documentation:**
- This file: Task Group 2 implementation instructions

## Notes

- The operator uses minimal resources (200m CPU, 512Mi memory) with limits (500m CPU, 1Gi memory)
- The operator runs as a non-root user (UID 65532) for security
- Health probes ensure the operator is functioning correctly
- The operator is deployed as a single replica (not HA) - sufficient for homelab use
- All configurations follow your project's patterns from nginx-ingress.yaml and vault-deployment.yaml

## Questions or Issues?

If you encounter issues not covered in the troubleshooting section:
1. Check operator logs in detail
2. Review Tailscale admin console for device status
3. Verify all prerequisites were completed
4. Check network connectivity between cluster and Tailscale services
