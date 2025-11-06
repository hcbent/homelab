# Kubespray Cluster Deployment - COMPLETE

**Date**: 2025-11-05
**Status**: ✅ Cluster and Platform Components Deployed

---

## Deployment Summary

The kubespray Kubernetes cluster has been successfully deployed with all core platform components operational.

### Cluster Information

**Nodes**: 6 nodes total
- **Control Plane**: km01, km02, km03 (all Ready)
- **Workers**: kube01, kube02, kube03 (all Ready)

**Kubernetes Version**: v1.33.4

**Access**:
```bash
kubectl --kubeconfig ~/.kube/config-kubespray get nodes
```

---

## Platform Components Deployed

### ✅ 1. MetalLB LoadBalancer
- **Namespace**: `metallb-system`
- **Status**: Running
- **IP Pool**: 192.168.10.100-192.168.10.150 (same subnet as nodes)
- **Configuration**: Layer 2 mode with IPAddressPool and L2Advertisement

**Verification**:
```bash
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n metallb-system
kubectl --kubeconfig ~/.kube/config-kubespray get ipaddresspool -n metallb-system
```

**Services using LoadBalancer**:
- ArgoCD Server: 192.168.10.100
- Traefik: 192.168.10.101

---

### ✅ 2. ArgoCD GitOps Platform
- **Namespace**: `argocd`
- **Status**: Running
- **UI Access**: https://192.168.10.100
- **Username**: `admin`
- **Password**: `y-PKuxulZTdbidoV`

**Credentials saved at**: `/tmp/argocd-access.txt`

**Verification**:
```bash
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n argocd
```

**Access UI**:
Open your browser to: https://192.168.10.100
(Accept the self-signed certificate warning)

---

### ✅ 3. Traefik Ingress Controller
- **Namespace**: `traefik`
- **Status**: Running (2 replicas)
- **LoadBalancer IP**: 192.168.10.101
- **Ports**:
  - HTTP: 80
  - HTTPS: 443

**Verification**:
```bash
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n traefik
kubectl --kubeconfig ~/.kube/config-kubespray get svc -n traefik
```

**Dashboard Access**:
```bash
kubectl --kubeconfig ~/.kube/config-kubespray port-forward -n traefik svc/traefik 9000:9000
# Then access: http://localhost:9000/dashboard/
```

---

### ✅ 4. cert-manager Configuration
- **Namespace**: `cert-manager` (deployed by kubespray)
- **Status**: Running
- **ClusterIssuers Created**:
  - `selfsigned-cluster-issuer` - For creating the internal CA
  - `ca-cluster-issuer` - For issuing certificates from internal CA

**Internal CA Certificate**: `internal-ca` in `cert-manager` namespace

**Verification**:
```bash
kubectl --kubeconfig ~/.kube/config-kubespray get clusterissuer
kubectl --kubeconfig ~/.kube/config-kubespray get certificate -n cert-manager
```

**Request a certificate**:
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: example-cert
  namespace: default
spec:
  secretName: example-cert-tls
  issuerRef:
    name: ca-cluster-issuer
    kind: ClusterIssuer
  dnsNames:
    - example.lab.thewortmans.org
```

---

### ⏸️ 5. Democratic CSI (Pending FreeNAS Configuration)
- **Status**: Configuration files created, NOT deployed yet
- **Reason**: Requires FreeNAS credentials from Vault
- **Files Ready**:
  - `/Users/bret/git/homelab/k8s/democratic-csi/namespace.yaml`
  - `/Users/bret/git/homelab/k8s/democratic-csi/values-iscsi.yaml`
  - `/Users/bret/git/homelab/k8s/democratic-csi/values-nfs.yaml`
  - `/Users/bret/git/homelab/k8s/democratic-csi/README.md`

**To Deploy**:
1. Update values files with actual FreeNAS IP and API endpoint
2. Create secrets with FreeNAS credentials from Vault
3. Deploy via Helm or ArgoCD

**See**: `/Users/bret/git/homelab/k8s/democratic-csi/README.md` for detailed instructions

---

## Current Cluster State

### Namespaces
```
argocd              - ArgoCD GitOps platform
cert-manager        - Certificate management
default             - Default namespace
kube-node-lease     - Node heartbeat
kube-public         - Public cluster info
kube-system         - Core Kubernetes components
metallb-system      - MetalLB load balancer
traefik             - Ingress controller
```

### All Pods Status
Run to verify all pods are healthy:
```bash
kubectl --kubeconfig ~/.kube/config-kubespray get pods -A
```

Expected: All pods in Running status except completed init containers.

---

## Known Issues and Limitations

### 1. ArgoCD GitOps Repository Access

**Issue**: ArgoCD cannot access the private GitHub repository (wortmanb/homelab) for GitOps automation.

**Error**: `authentication required` when ArgoCD tries to sync applications

**Impact**:
- ArgoCD Applications cannot sync from GitHub
- Platform components were deployed manually instead of via GitOps
- App of Apps pattern is not functional

**Solutions** (choose one):

**Option A: Configure SSH Key for ArgoCD** (Recommended for private repos)
```bash
# 1. Generate SSH key for ArgoCD
ssh-keygen -t ed25519 -C "argocd@homelab" -f ~/.ssh/argocd_ed25519 -N ""

# 2. Add public key to GitHub
# Go to: https://github.com/wortmanb/homelab/settings/keys
# Add: ~/.ssh/argocd_ed25519.pub

# 3. Create secret in ArgoCD namespace
kubectl --kubeconfig ~/.kube/config-kubespray create secret generic argocd-repo-creds \
  -n argocd \
  --from-file=sshPrivateKey=~/.ssh/argocd_ed25519

# 4. Configure repository in ArgoCD
kubectl --kubeconfig ~/.kube/config-kubespray apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: homelab-repo
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: git@github.com:wortmanb/homelab.git
  sshPrivateKey: |
$(cat ~/.ssh/argocd_ed25519 | sed 's/^/    /')
EOF

# 5. Reapply ArgoCD applications
kubectl --kubeconfig ~/.kube/config-kubespray apply -f /Users/bret/git/homelab/k8s/argocd/argocd-apps/
```

**Option B: Use Personal Access Token** (HTTPS)
```bash
# 1. Create GitHub Personal Access Token
# Go to: https://github.com/settings/tokens
# Scopes: repo (full control)

# 2. Create secret with token
kubectl --kubeconfig ~/.kube/config-kubespray apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: homelab-repo
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: https://github.com/wortmanb/homelab.git
  password: YOUR_GITHUB_TOKEN_HERE
  username: wortmanb
EOF

# 3. Reapply ArgoCD applications
kubectl --kubeconfig ~/.kube/config-kubespray apply -f /Users/bret/git/homelab/k8s/argocd/argocd-apps/
```

**Option C: Make Repository Public** (Not recommended for homelab with secrets)

### 2. Democratic CSI Not Deployed

**Reason**: Requires FreeNAS credentials and configuration

**To Deploy**:
1. Verify Vault has FreeNAS credentials:
   ```bash
   vault kv get secret/homelab/freenas/credentials
   ```
2. Update values files with actual FreeNAS IP
3. Create Kubernetes secrets with credentials
4. Deploy via Helm

**See**: `/Users/bret/git/homelab/k8s/democratic-csi/README.md`

---

## Next Steps

### Immediate Actions

1. **Configure ArgoCD Repository Access** (if you want GitOps)
   - Choose Option A or B above
   - Test by reapplying ArgoCD applications

2. **Deploy Democratic CSI** (if you need persistent storage)
   - Follow instructions in `/Users/bret/git/homelab/k8s/democratic-csi/README.md`
   - Verify iSCSI is installed on worker nodes
   - Create secrets with FreeNAS credentials

3. **Test Platform Components**
   - Create a test Ingress with Traefik
   - Request a test certificate from cert-manager
   - Create a LoadBalancer service to test MetalLB

### Future Enhancements

1. **Enable Monitoring**
   - Deploy Prometheus + Grafana stack
   - Configure ServiceMonitors for platform components

2. **Configure Backup**
   - Set up Velero for cluster backups
   - Configure etcd snapshot automation

3. **Deploy Applications**
   - Use ArgoCD to deploy your applications
   - Create Application manifests in `k8s/` directory

4. **Harden Security**
   - Configure Network Policies
   - Enable Pod Security Standards
   - Set up External Secrets Operator for Vault integration

---

## Verification Commands

### Complete Health Check
```bash
# All nodes ready
kubectl --kubeconfig ~/.kube/config-kubespray get nodes

# All pods running
kubectl --kubeconfig ~/.kube/config-kubespray get pods -A

# Platform component status
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n metallb-system
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n argocd
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n traefik
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n cert-manager

# MetalLB configuration
kubectl --kubeconfig ~/.kube/config-kubespray get ipaddresspool -n metallb-system
kubectl --kubeconfig ~/.kube/config-kubespray get l2advertisement -n metallb-system

# cert-manager configuration
kubectl --kubeconfig ~/.kube/config-kubespray get clusterissuer
kubectl --kubeconfig ~/.kube/config-kubespray get certificate -n cert-manager

# Services with LoadBalancer IPs
kubectl --kubeconfig ~/.kube/config-kubespray get svc -A | grep LoadBalancer
```

### etcd Health
```bash
ssh bret@192.168.10.234 -i /Users/bret/.ssh/github_rsa
sudo ETCDCTL_API=3 etcdctl endpoint health \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/node-km01.pem \
  --key=/etc/ssl/etcd/ssl/node-km01-key.pem
```

---

## Documentation References

### Deployment Documentation
- **Main Deployment Guide**: `/Users/bret/git/homelab/kubespray/DEPLOYMENT-PROCEDURES.md`
- **Bootstrap Guide**: `/Users/bret/git/homelab/kubespray/BOOTSTRAP-PLATFORM.md`
- **Deployment Fix Summary**: `/Users/bret/git/homelab/kubespray/DEPLOYMENT-FIX-SUMMARY.md`

### Platform Component Documentation
- **ArgoCD**: `/Users/bret/git/homelab/k8s/argocd/README.md`
- **MetalLB**: `/Users/bret/git/homelab/k8s/metallb/README.md`
- **Traefik**: `/Users/bret/git/homelab/k8s/traefik/README.md`
- **cert-manager**: `/Users/bret/git/homelab/k8s/cert-manager/README.md`
- **Democratic CSI**: `/Users/bret/git/homelab/k8s/democratic-csi/README.md`

### Operational Guides
- **Operations**: `/Users/bret/git/homelab/docs/KUBESPRAY-OPERATIONS.md`
- **Backup/Restore**: `/Users/bret/git/homelab/docs/KUBESPRAY-BACKUP-RESTORE.md`
- **Troubleshooting**: `/Users/bret/git/homelab/docs/KUBESPRAY-TROUBLESHOOTING.md`
- **Architecture**: `/Users/bret/git/homelab/docs/KUBESPRAY-ARCHITECTURE.md`
- **Configuration Reference**: `/Users/bret/git/homelab/docs/KUBESPRAY-CONFIG-REFERENCE.md`

---

## Success Criteria - Status

- ✅ Cluster deployed with 6 nodes (3 control plane, 3 workers)
- ✅ All nodes in Ready state
- ✅ etcd distributed across 3 control plane nodes
- ✅ Calico CNI operational
- ✅ CoreDNS functional
- ✅ cert-manager deployed and configured
- ✅ MetalLB deployed with IP pool configured
- ✅ ArgoCD deployed and accessible
- ✅ Traefik ingress controller deployed
- ✅ ClusterIssuers configured for certificate management
- ⏸️ Democratic CSI prepared (awaiting FreeNAS credentials)
- ⏸️ ArgoCD GitOps (awaiting repository access configuration)

---

## Contact and Support

For issues with kubespray cluster:
- Review troubleshooting guide: `/Users/bret/git/homelab/docs/KUBESPRAY-TROUBLESHOOTING.md`
- Check kubespray documentation: https://kubespray.io/
- Review Kubernetes documentation: https://kubernetes.io/docs/

---

*Deployment completed: 2025-11-05*
*Next actions: Configure ArgoCD repository access, Deploy Democratic CSI*
