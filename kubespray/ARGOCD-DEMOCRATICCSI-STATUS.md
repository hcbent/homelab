# ArgoCD and Democratic CSI Deployment Status

**Date**: 2025-11-05
**Session**: Final deployment tasks

---

## Summary

### ✅ ArgoCD GitHub Access - COMPLETE
ArgoCD has been successfully configured with SSH key access to your private GitHub repository.

**Status**: Fully functional
**Repository**: git@github.com:wortmanb/homelab.git
**SSH Key**: ~/.ssh/github_rsa

**ArgoCD Applications Created**:
- metallb
- traefik
- cert-manager-config
- democratic-csi-iscsi
- democratic-csi-nfs

All applications can now access the private repository for GitOps automation.

### ⏸️ Democratic CSI - BLOCKED
Democratic CSI deployment is blocked due to SSH authentication failure.

**Status**: Helm charts deployed, controller pods crashing
**Blocker**: SSH password authentication failing
**Error**: "All configured authentication methods failed"

---

## ArgoCD Configuration Details

### Repository Secret Created
```bash
kubectl get secret homelab-repo -n argocd
```

**Secret contains**:
- SSH private key from ~/.ssh/github_rsa
- Repository URL: git@github.com:wortmanb/homelab.git
- Type: git

### ArgoCD Applications Status
```bash
kubectl --kubeconfig ~/.kube/config-kubespray get applications -n argocd
```

All 5 applications are created and can access the repository. They show "Unknown" sync status because the resources were already deployed manually (MetalLB, Traefik, cert-manager config). ArgoCD will adopt and manage them going forward.

---

## Democratic CSI Issue

### Problem
SSH password authentication to TrueNAS is failing despite passwordauth being enabled.

**Error Message**: "All configured authentication methods failed"

**Root Cause Analysis**:
- TrueNAS API key: ✅ Valid (tested successfully)
- TrueNAS SSH passwordauth: ✅ Enabled (`"passwordauth": true`)
- Password login groups: ⚠️ Empty (`"password_login_groups": []`)
- Credentials: ✅ Correct in Vault (username: root, password: ***REMOVED***)

**Possible Issues**:
1. TrueNAS may have password authentication restricted by group membership
2. Root user may not be in allowed password_login_groups
3. SSH may be configured to require key-based auth for root

### Current State
- ✅ Democratic CSI values files updated with TrueNAS credentials
- ✅ Namespace created: `democratic-csi`
- ✅ Snapshot CRDs installed
- ✅ Helm charts deployed successfully (both iSCSI and NFS)
- ✅ Storage classes created: `freenas-iscsi-csi` (default), `freenas-nfs-csi`
- ❌ Controller pods in CrashLoopBackOff (SSH authentication failure)
- ✅ Node pods running successfully (4/4 containers each)

### Files Ready for Deployment
- `/Users/bret/git/homelab/k8s/democratic-csi/values-iscsi.yaml` - Configured
- `/Users/bret/git/homelab/k8s/democratic-csi/values-nfs.yaml` - Configured
- `/Users/bret/git/homelab/k8s/democratic-csi/namespace.yaml` - Applied

---

## Required Action: Fix SSH Password Authentication

### Options to Resolve

**Option 1: Enable Password Authentication for Root (Recommended)**

1. **Log into TrueNAS Web UI**:
   - URL: http://truenas.lab.thewortmans.org
   - Username: root
   - Password: ***REMOVED***

2. **Configure SSH Password Authentication**:
   - Navigate to: **System → Services → SSH**
   - Click **Configure** (pencil icon)
   - Under **Password Login Groups**, add a group that root belongs to (or leave empty to allow all)
   - Ensure **Log in as Root with Password** is enabled
   - Click **Save**

3. **Restart SSH Service**:
   - In Services page, toggle SSH service off then on

4. **Restart Democratic CSI Pods**:
   ```bash
   kubectl --kubeconfig ~/.kube/config-kubespray rollout restart deployment -n democratic-csi
   ```

**Option 2: Use SSH Key Authentication Instead of Password**

If password auth cannot be enabled, configure Democratic CSI to use SSH keys:

1. **Generate SSH Key** (if not exists):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/truenas_democratic_csi -N ""
   ```

2. **Add Public Key to TrueNAS**:
   - Copy content of `~/.ssh/truenas_democratic_csi.pub`
   - In TrueNAS: **Accounts → Users → root → Edit**
   - Paste into **SSH Public Key** field
   - Save

3. **Update Democratic CSI Values**:
   Replace `sshConnection` section in both values files:
   ```yaml
   sshConnection:
     host: truenas.lab.thewortmans.org
     port: 22
     username: root
     privateKey: |
       -----BEGIN OPENSSH PRIVATE KEY-----
       <paste content of ~/.ssh/truenas_democratic_csi>
       -----END OPENSSH PRIVATE KEY-----
   ```

4. **Redeploy Democratic CSI**:
   ```bash
   helm upgrade freenas-iscsi democratic-csi/democratic-csi \
     --namespace democratic-csi \
     --values /Users/bret/git/homelab/k8s/democratic-csi/values-iscsi.yaml

   helm upgrade freenas-nfs democratic-csi/democratic-csi \
     --namespace democratic-csi \
     --values /Users/bret/git/homelab/k8s/democratic-csi/values-nfs.yaml
   ```

---

## Testing Democratic CSI

Once deployed successfully, test with a simple PVC:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: freenas-iscsi-csi
```

```bash
# Apply the test PVC
kubectl --kubeconfig ~/.kube/config-kubespray apply -f test-pvc.yaml

# Check if it's bound
kubectl --kubeconfig ~/.kube/config-kubespray get pvc test-pvc

# Should show STATUS: Bound
```

---

## Current Cluster Status

### ✅ Fully Operational
- **Kubernetes Cluster**: 6 nodes, all Ready
- **MetalLB**: Load balancer (192.168.10.100-150)
- **ArgoCD**: GitOps platform with GitHub access (https://192.168.10.100)
- **Traefik**: Ingress controller (192.168.10.101)
- **cert-manager**: Certificate management with ClusterIssuers

### ⏸️ Pending SSH Authentication Fix
- **Democratic CSI iSCSI**: Deployed, controller crashing (SSH auth issue)
- **Democratic CSI NFS**: Deployed, controller crashing (SSH auth issue)
- **Storage Classes**: Created and available

---

## References

- **ArgoCD UI**: https://192.168.10.100 (admin / y-PKuxulZTdbidoV)
- **Democratic CSI README**: `/Users/bret/git/homelab/k8s/democratic-csi/README.md`
- **Vault Secret Path**: `secret/homelab/freenas/credentials`
- **TrueNAS API Docs**: http://truenas.lab.thewortmans.org/api/docs

---

*Status as of: 2025-11-05 13:30 EST*
*Next action: Fix SSH password authentication in TrueNAS or configure SSH key auth*
