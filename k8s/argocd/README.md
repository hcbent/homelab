# ArgoCD GitOps Configuration

This directory contains the configuration for ArgoCD, which provides GitOps-based continuous delivery for Kubernetes.

## Overview

ArgoCD enables GitOps workflows by:
- **Declarative Configuration**: Applications defined in Git repositories
- **Automated Sync**: Automatically syncs cluster state with Git repository
- **Drift Detection**: Detects when cluster state differs from Git
- **Multi-Source Support**: Helm charts, Kustomize, plain YAML manifests
- **Web UI**: Visual dashboard for application management
- **RBAC**: Fine-grained access control for applications and resources

## Architecture

```
Git Repository (Source of Truth)
       |
       v
ArgoCD Application Controller
       |
       v
Kubernetes Cluster (Desired State)
```

## Prerequisites

### MetalLB LoadBalancer

ArgoCD server uses a LoadBalancer service to expose the UI. Ensure MetalLB is deployed:

```bash
kubectl get pods -n metallb-system
kubectl get ipaddresspool -n metallb-system
```

### Git Repository Access

ArgoCD needs access to your Git repository. You can use:
- **HTTPS**: Public repositories or with tokens
- **SSH**: Private repositories with SSH keys

## Configuration Files

### `namespace.yaml`
Creates the `argocd` namespace for all ArgoCD components.

### `values.yaml`
Helm values for ArgoCD deployment:
- **Server**: Web UI and API (LoadBalancer service)
- **Repository Server**: Manages Git repository connections
- **Application Controller**: Syncs applications to cluster
- **Redis**: Caching layer
- **ApplicationSet Controller**: Manages application templates

## Deployment

### Manual Deployment

1. **Create Namespace**:
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/argocd/namespace.yaml
```

2. **Add Helm Repository**:
```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
```

3. **Deploy ArgoCD**:
```bash
helm install argocd argo/argo-cd \
  -n argocd \
  -f /Users/bret/git/homelab/k8s/argocd/values.yaml
```

4. **Wait for Deployment**:
```bash
kubectl wait --namespace argocd \
  --for=condition=available deployment/argocd-server \
  --timeout=120s
```

### Alternative: Direct Manifest Installation

If you prefer not to use Helm:

```bash
# Install ArgoCD
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Patch service to LoadBalancer
kubectl patch svc argocd-server -n argocd -p '{"spec": {"type": "LoadBalancer"}}'
```

## Verification

### Check Deployment Status

```bash
# Check ArgoCD pods
kubectl get pods -n argocd

# Expected output:
# NAME                                  READY   STATUS    RESTARTS   AGE
# argocd-application-controller-xxxxx   1/1     Running   0          2m
# argocd-applicationset-controller-xxx  1/1     Running   0          2m
# argocd-dex-server-xxxxx               1/1     Running   0          2m
# argocd-redis-xxxxx                    1/1     Running   0          2m
# argocd-repo-server-xxxxx              1/1     Running   0          2m
# argocd-server-xxxxx                   1/1     Running   0          2m
```

### Get LoadBalancer IP

```bash
kubectl get svc -n argocd argocd-server

# Expected output:
# NAME            TYPE           CLUSTER-IP      EXTERNAL-IP       PORT(S)
# argocd-server   LoadBalancer   10.233.x.x      192.168.100.20    80:30080/TCP,443:30443/TCP
```

## Access ArgoCD UI

### Get Initial Admin Password

```bash
# Retrieve initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d; echo

# Username: admin
# Password: <output from above command>
```

### Access Web UI

**Via LoadBalancer IP**:
```bash
# Get LoadBalancer IP
ARGOCD_IP=$(kubectl get svc -n argocd argocd-server -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "ArgoCD UI: https://${ARGOCD_IP}"
```

Access: `https://192.168.100.20` (replace with your actual IP)

**Note**: You'll see a certificate warning since ArgoCD uses a self-signed certificate by default.

**Via Port Forward** (for initial access):
```bash
kubectl port-forward svc/argocd-server -n argocd 8080:443
```
Access: `https://localhost:8080`

**Via Ingress** (if configured in values.yaml):
Update DNS to point to Traefik LoadBalancer IP, then access via hostname.

### Login via CLI

```bash
# Install ArgoCD CLI
# macOS
brew install argocd

# Linux
curl -sSL -o argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
chmod +x argocd
sudo mv argocd /usr/local/bin/

# Login to ArgoCD
ARGOCD_IP=$(kubectl get svc -n argocd argocd-server -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
argocd login ${ARGOCD_IP} --insecure

# Enter username: admin
# Enter password: <from kubectl command above>

# Change admin password
argocd account update-password
```

## Configure Repository Access

### Add Git Repository via CLI

**HTTPS (Public Repository)**:
```bash
argocd repo add https://github.com/wortmanb/homelab.git
```

**HTTPS (Private Repository with Token)**:
```bash
argocd repo add https://github.com/wortmanb/homelab.git \
  --username <username> \
  --password <token>
```

**SSH (Private Repository)**:
```bash
# Generate SSH key (if not already done)
ssh-keygen -t rsa -b 4096 -f ~/.ssh/argocd_rsa

# Add public key to GitHub (Settings > SSH Keys)
cat ~/.ssh/argocd_rsa.pub

# Add repository with SSH key
argocd repo add git@github.com:wortmanb/homelab.git \
  --ssh-private-key-path ~/.ssh/argocd_rsa
```

### Add Repository via UI

1. Go to **Settings** > **Repositories**
2. Click **Connect Repo**
3. Select connection method (HTTPS or SSH)
4. Enter repository URL
5. Provide credentials (token or SSH key)
6. Click **Connect**

### Add Helm Repository

```bash
# Via CLI
argocd repo add https://traefik.github.io/charts --type helm --name traefik

# Add multiple Helm repos
argocd repo add https://metallb.github.io/metallb --type helm --name metallb
argocd repo add https://democratic-csi.github.io/charts/ --type helm --name democratic-csi
argocd repo add https://charts.jetstack.io --type helm --name jetstack
```

## Deploy Applications

### Create Application via CLI

```bash
# Example: Deploy Democratic CSI iSCSI
argocd app create democratic-csi-iscsi \
  --repo https://democratic-csi.github.io/charts/ \
  --helm-chart democratic-csi \
  --revision 0.14.6 \
  --helm-set-file values=/Users/bret/git/homelab/k8s/democratic-csi/values-iscsi.yaml \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace democratic-csi \
  --sync-policy automated \
  --sync-option CreateNamespace=true
```

### Create Application via YAML Manifest

Create an Application manifest:

```yaml
# democratic-csi-iscsi-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: democratic-csi-iscsi
  namespace: argocd
spec:
  project: default
  destination:
    namespace: democratic-csi
    server: https://kubernetes.default.svc
  sources:
    - repoURL: https://democratic-csi.github.io/charts/
      targetRevision: 0.14.6
      chart: democratic-csi
      helm:
        valueFiles:
          - $values/k8s/democratic-csi/values-iscsi.yaml
    - repoURL: git@github.com/wortmanb/homelab.git
      path: k8s/democratic-csi
      targetRevision: main
      ref: values
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
    automated:
      prune: true
      selfHeal: true
```

Apply the manifest:
```bash
kubectl apply -f democratic-csi-iscsi-app.yaml
```

### App of Apps Pattern

Create a parent application that manages other applications:

```yaml
# platform-apps.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: platform-apps
  namespace: argocd
spec:
  project: default
  destination:
    namespace: argocd
    server: https://kubernetes.default.svc
  source:
    repoURL: git@github.com/wortmanb/homelab.git
    path: k8s/argocd/argocd-apps
    targetRevision: main
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

Place all application manifests in `k8s/argocd/argocd-apps/` directory.

## Example Application Manifests

### MetalLB Application

```yaml
# k8s/argocd/argocd-apps/metallb-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: metallb
  namespace: argocd
spec:
  project: default
  destination:
    namespace: metallb-system
    server: https://kubernetes.default.svc
  sources:
    - repoURL: https://metallb.github.io/metallb
      targetRevision: 0.14.8
      chart: metallb
      helm:
        valueFiles:
          - $values/k8s/metallb/values.yaml
    - repoURL: git@github.com/wortmanb/homelab.git
      path: k8s/metallb
      targetRevision: main
      ref: values
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
    automated:
      prune: true
      selfHeal: true
```

### Traefik Application

```yaml
# k8s/argocd/argocd-apps/traefik-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: traefik
  namespace: argocd
spec:
  project: default
  destination:
    namespace: traefik
    server: https://kubernetes.default.svc
  sources:
    - repoURL: https://traefik.github.io/charts
      targetRevision: 30.0.2
      chart: traefik
      helm:
        valueFiles:
          - $values/k8s/traefik/values.yaml
    - repoURL: git@github.com/wortmanb/homelab.git
      path: k8s/traefik
      targetRevision: main
      ref: values
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
    automated:
      prune: true
      selfHeal: true
```

## Application Management

### Sync Application

```bash
# Sync via CLI
argocd app sync <app-name>

# Sync specific resource
argocd app sync <app-name> --resource <kind>:<name>

# Sync with prune (delete resources not in git)
argocd app sync <app-name> --prune
```

### View Application Status

```bash
# List all applications
argocd app list

# Get application details
argocd app get <app-name>

# View application history
argocd app history <app-name>

# View application logs
argocd app logs <app-name>
```

### Rollback Application

```bash
# Rollback to previous version
argocd app rollback <app-name>

# Rollback to specific revision
argocd app rollback <app-name> <revision-id>
```

### Delete Application

```bash
# Delete application (keeps resources in cluster)
argocd app delete <app-name>

# Delete application and all resources
argocd app delete <app-name> --cascade
```

## Sync Policies

### Manual Sync

Application must be synced manually:
```yaml
syncPolicy: {}
```

### Automated Sync

Application syncs automatically when Git changes:
```yaml
syncPolicy:
  automated: {}
```

### Automated Sync with Prune

Automatically delete resources removed from Git:
```yaml
syncPolicy:
  automated:
    prune: true
```

### Automated Sync with Self-Heal

Automatically revert manual changes to cluster:
```yaml
syncPolicy:
  automated:
    prune: true
    selfHeal: true
```

## Troubleshooting

### Application OutOfSync

Check diff between Git and cluster:
```bash
argocd app diff <app-name>
```

Sync the application:
```bash
argocd app sync <app-name>
```

### Sync Failed

Check application events:
```bash
argocd app get <app-name>
kubectl describe application <app-name> -n argocd
```

Check ArgoCD logs:
```bash
kubectl logs -n argocd deployment/argocd-application-controller
kubectl logs -n argocd deployment/argocd-server
kubectl logs -n argocd deployment/argocd-repo-server
```

Common issues:
- Repository credentials invalid
- Helm chart version not found
- Invalid YAML syntax in manifests
- Insufficient RBAC permissions
- Resource validation failures

### Repository Connection Failed

Test repository connection:
```bash
argocd repo get <repo-url>
```

Re-add repository with correct credentials:
```bash
argocd repo rm <repo-url>
argocd repo add <repo-url> --ssh-private-key-path ~/.ssh/argocd_rsa
```

### Certificate Errors

If using self-signed certificates:
```bash
# Login with --insecure flag
argocd login <argocd-server> --insecure

# Or add certificate to system trust store
```

### Webhook Not Working

For automatic sync on Git push, configure webhooks:
1. In ArgoCD UI: Settings > Projects > default > Webhook
2. Copy webhook URL
3. In GitHub: Repo > Settings > Webhooks > Add webhook
4. Paste webhook URL
5. Select "application/json" content type
6. Select events: "Just the push event"

## Security Best Practices

1. **Change Default Admin Password**: Immediately after installation
2. **Use SSH Keys for Private Repos**: More secure than passwords/tokens
3. **Enable RBAC**: Configure role-based access control
4. **Use Projects**: Separate applications by team or environment
5. **Enable Audit Logs**: Track all changes
6. **Use TLS for UI**: Configure cert-manager certificate
7. **Limit Network Access**: Use network policies or firewall rules
8. **Regular Updates**: Keep ArgoCD up-to-date
9. **Secret Management**: Use sealed-secrets or external-secrets-operator
10. **Review Sync Policies**: Ensure automated sync is safe for your use case

## Maintenance

### Update Admin Password

```bash
argocd account update-password --current-password <old> --new-password <new>
```

### Backup ArgoCD Configuration

```bash
# Export all applications
argocd app list -o yaml > argocd-apps-backup.yaml

# Export all projects
argocd proj list -o yaml > argocd-projects-backup.yaml

# Backup ArgoCD namespace
kubectl get all,secrets,configmaps -n argocd -o yaml > argocd-namespace-backup.yaml
```

### Upgrade ArgoCD

```bash
# Update Helm repo
helm repo update

# Upgrade ArgoCD
helm upgrade argocd argo/argo-cd \
  -n argocd \
  -f /Users/bret/git/homelab/k8s/argocd/values.yaml

# Verify upgrade
kubectl rollout status deployment/argocd-server -n argocd
```

### Uninstall ArgoCD

```bash
# WARNING: This will remove all application definitions (but not the applications themselves)

# Delete all applications (optionally with --cascade to delete resources)
argocd app delete --all

# Uninstall Helm chart
helm uninstall argocd -n argocd

# Delete namespace
kubectl delete namespace argocd
```

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Update Image Tag
on:
  push:
    branches: [main]
    paths: ['app/**']

jobs:
  update-gitops:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Update image tag
        run: |
          # Build and push image
          IMAGE_TAG=${{ github.sha }}
          # Update values file
          sed -i "s/tag: .*/tag: ${IMAGE_TAG}/" k8s/myapp/values.yaml
          git commit -am "Update image tag to ${IMAGE_TAG}"
          git push
      # ArgoCD will detect the change and sync automatically
```

## References

- [ArgoCD Official Documentation](https://argo-cd.readthedocs.io/)
- [ArgoCD Helm Chart](https://github.com/argoproj/argo-helm/tree/main/charts/argo-cd)
- [ArgoCD Best Practices](https://argo-cd.readthedocs.io/en/stable/user-guide/best_practices/)
- [ArgoCD ApplicationSet](https://argo-cd.readthedocs.io/en/stable/user-guide/application-set/)
