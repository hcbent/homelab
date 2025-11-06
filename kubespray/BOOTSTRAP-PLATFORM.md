# Bootstrap Platform Components

**Status**: Ready to execute
**Date**: 2025-11-05

---

## Overview

This guide explains how to bootstrap the kubespray cluster platform components using ArgoCD for GitOps-based deployment.

## What's Been Prepared

### 1. Ansible Playbook Created
- **File**: `/Users/bret/git/homelab/ansible/playbooks/bootstrap_argocd.yml`
- **Purpose**: Deploy MetalLB and ArgoCD to enable GitOps

### 2. ArgoCD Configuration Fixed
- **Fixed**: All ArgoCD Application manifests now use HTTPS instead of SSH
- **Location**: `/Users/bret/git/homelab/k8s/argocd/`
- **Files updated**:
  - `platform-apps.yaml` (App of Apps)
  - `argocd-apps/metallb-app.yaml`
  - `argocd-apps/traefik-app.yaml`
  - `argocd-apps/democratic-csi-iscsi-app.yaml`
  - `argocd-apps/democratic-csi-nfs-app.yaml`
  - `argocd-apps/cert-manager-config-app.yaml`

### 3. Platform Components Ready for Deployment
All configuration files, Helm values, and ArgoCD Applications are ready:
- ✅ MetalLB (Load Balancer)
- ✅ ArgoCD (GitOps)
- ✅ Democratic CSI (iSCSI + NFS storage)
- ✅ Traefik (Ingress Controller)
- ✅ cert-manager configuration (ClusterIssuers and CA)

---

## Deployment Steps

### Step 1: Bootstrap ArgoCD (via Ansible)

Run the Ansible playbook to deploy MetalLB and ArgoCD:

```bash
cd /Users/bret/git/homelab/ansible/

ansible-playbook -i ../kubespray/inventory/homelab/hosts.ini playbooks/bootstrap_argocd.yml
```

**What this does:**
1. Creates temporary directory on km01 for config files
2. Copies MetalLB and ArgoCD configuration files from local machine to km01
3. Verifies kubectl and Helm are available on km01
4. Creates MetalLB namespace and deploys MetalLB via Helm
5. Applies MetalLB IPAddressPool (192.168.100.0/24)
6. Applies MetalLB L2Advertisement
7. Creates ArgoCD namespace and deploys ArgoCD via Helm
8. Waits for ArgoCD to be ready
9. Retrieves ArgoCD admin password and LoadBalancer IP
10. Saves credentials to `/tmp/argocd-access.txt` on your local machine

**Expected duration**: 5-10 minutes

**What to watch for:**
- MetalLB controller pod becomes Ready
- ArgoCD server pod becomes Ready
- ArgoCD server gets a LoadBalancer IP assigned

### Step 2: Verify ArgoCD Access

After the playbook completes, check the credentials:

```bash
cat /tmp/argocd-access.txt
```

Access the ArgoCD UI in your browser:
- URL will be displayed by the playbook (e.g., `http://192.168.100.X`)
- Username: `admin`
- Password: (from `/tmp/argocd-access.txt`)

### Step 3: Deploy Platform Applications

Deploy all platform components via ArgoCD's App of Apps pattern:

```bash
kubectl --kubeconfig ~/.kube/config-kubespray apply -f /Users/bret/git/homelab/k8s/argocd/platform-apps.yaml
```

**What this deploys** (via GitOps):
1. **MetalLB** (sync-wave: 2) - Already deployed manually, ArgoCD will adopt it
2. **Democratic CSI iSCSI** (sync-wave: 3) - Primary storage class
3. **Democratic CSI NFS** (sync-wave: 3) - Shared storage class
4. **Traefik** (sync-wave: 4) - Ingress controller
5. **cert-manager config** (sync-wave: 5) - ClusterIssuers and internal CA

**Expected duration**: 10-15 minutes

### Step 4: Monitor Deployment

Watch ArgoCD applications sync:

```bash
# Watch applications
kubectl --kubeconfig ~/.kube/config-kubespray get applications -n argocd -w

# Or use ArgoCD CLI
argocd app list

# Or watch in the ArgoCD UI
```

### Step 5: Verify All Components

Check that all components are deployed and healthy:

```bash
# Check namespaces
kubectl --kubeconfig ~/.kube/config-kubespray get namespaces

# Check MetalLB
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n metallb-system
kubectl --kubeconfig ~/.kube/config-kubespray get ipaddresspool -n metallb-system

# Check Democratic CSI
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n democratic-csi
kubectl --kubeconfig ~/.kube/config-kubespray get storageclass

# Check Traefik
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n traefik
kubectl --kubeconfig ~/.kube/config-kubespray get svc -n traefik

# Check cert-manager
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n cert-manager
kubectl --kubeconfig ~/.kube/config-kubespray get clusterissuer

# Check ArgoCD applications
kubectl --kubeconfig ~/.kube/config-kubespray get applications -n argocd
```

---

## Expected Results

After successful deployment, you should have:

### Namespaces
- `argocd` - ArgoCD components
- `metallb-system` - MetalLB load balancer
- `democratic-csi` - Storage CSI drivers
- `traefik` - Ingress controller
- `cert-manager` - Certificate management (already existed)

### Storage Classes
- `freenas-iscsi-csi` (default) - iSCSI block storage
- `freenas-nfs-csi` - NFS shared storage

### Services with LoadBalancer IPs
- `argocd-server` - ArgoCD UI/API
- `traefik` - Ingress controller

### ClusterIssuers
- `selfsigned-cluster-issuer` - For creating the internal CA
- `ca-cluster-issuer` - For issuing certificates

### Internal CA Certificate
- `internal-ca` in `cert-manager` namespace

---

## Troubleshooting

### ArgoCD playbook fails

**Check prerequisites:**
```bash
# Verify cluster is healthy
kubectl --kubeconfig ~/.kube/config-kubespray get nodes

# Verify SSH to km01
ssh bret@192.168.10.234 -i /Users/bret/.ssh/github_rsa
```

### ArgoCD doesn't get a LoadBalancer IP

**Check MetalLB:**
```bash
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n metallb-system
kubectl --kubeconfig ~/.kube/config-kubespray logs -n metallb-system -l app.kubernetes.io/component=controller
kubectl --kubeconfig ~/.kube/config-kubespray get ipaddresspool -n metallb-system
```

### ArgoCD application stuck in "Progressing"

**Check application details:**
```bash
kubectl --kubeconfig ~/.kube/config-kubespray describe application <app-name> -n argocd

# View application logs in ArgoCD UI or:
kubectl --kubeconfig ~/.kube/config-kubespray logs -n argocd -l app.kubernetes.io/name=argocd-application-controller
```

### Democratic CSI fails to provision volumes

**Check iSCSI on worker nodes:**
```bash
# SSH to each worker node
for node in kube01 kube02 kube03; do
  echo "=== $node ==="
  ssh bret@192.168.10.23[7-9] "sudo systemctl status iscsid"
done
```

**Check FreeNAS credentials:**
- Ensure Vault has credentials at `secret/homelab/freenas/credentials`
- Democratic CSI values files have placeholders that need actual FreeNAS IP and credentials

### Traefik not routing traffic

**Check Traefik deployment:**
```bash
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n traefik
kubectl --kubeconfig ~/.kube/config-kubespray logs -n traefik -l app.kubernetes.io/name=traefik
kubectl --kubeconfig ~/.kube/config-kubespray get svc -n traefik
```

---

## Next Steps After Deployment

1. **Configure Democratic CSI secrets** with actual FreeNAS credentials from Vault
2. **Test storage** by creating a test PVC
3. **Test Traefik** by creating a test Ingress
4. **Test cert-manager** by requesting a certificate
5. **Deploy applications** via ArgoCD from your homelab repository

---

## Important Notes

### MetalLB IP Pool
- **Range**: 192.168.100.0/24
- **Usage**: Services with `type: LoadBalancer` will get IPs from this range
- **Ensure**: This range doesn't conflict with your network's DHCP

### Democratic CSI Configuration
The current Democratic CSI values files have placeholder FreeNAS IPs and credentials.

**Before Democratic CSI will work**, you need to:
1. Update `k8s/democratic-csi/values-iscsi.yaml` with actual FreeNAS IP
2. Update `k8s/democratic-csi/values-nfs.yaml` with actual FreeNAS IP
3. Create secrets with FreeNAS API credentials (retrieved from Vault)

Refer to `/Users/bret/git/homelab/k8s/democratic-csi/README.md` for detailed instructions.

### ArgoCD App of Apps Pattern
The `platform-apps.yaml` creates an ArgoCD Application that watches the `k8s/argocd/argocd-apps/` directory. Any Application manifests added to that directory will be automatically deployed by ArgoCD.

This enables full GitOps: just commit new Application manifests to Git, and ArgoCD will deploy them.

---

## References

- **ArgoCD Documentation**: `/Users/bret/git/homelab/k8s/argocd/README.md`
- **MetalLB Documentation**: `/Users/bret/git/homelab/k8s/metallb/README.md`
- **Democratic CSI Documentation**: `/Users/bret/git/homelab/k8s/democratic-csi/README.md`
- **Traefik Documentation**: `/Users/bret/git/homelab/k8s/traefik/README.md`
- **cert-manager Documentation**: `/Users/bret/git/homelab/k8s/cert-manager/README.md`
- **Kubespray Deployment**: `/Users/bret/git/homelab/kubespray/DEPLOYMENT-PROCEDURES.md`

---

*Bootstrap procedures ready: 2025-11-05*
