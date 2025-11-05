# ArgoCD Applications

This directory contains ArgoCD Application manifests for deploying platform components and applications to the Kubernetes cluster.

## App of Apps Pattern

The `platform-apps.yaml` file in the parent directory (`k8s/argocd/`) serves as the "App of Apps" - a single application that manages all other applications in this directory.

### Deploy Platform Apps

```bash
# Apply the App of Apps manifest
kubectl apply -f /Users/bret/git/homelab/k8s/argocd/platform-apps.yaml

# This will automatically deploy all applications defined in this directory
```

## Application Manifests

### Platform Components

- **`democratic-csi-iscsi-app.yaml`**: iSCSI storage driver for block storage
- **`democratic-csi-nfs-app.yaml`**: NFS storage driver for shared storage
- **`metallb-app.yaml`**: LoadBalancer service implementation
- **`traefik-app.yaml`**: Ingress controller for HTTP/HTTPS routing
- **`cert-manager-config-app.yaml`**: cert-manager configuration (issuers, CA)

### Application Components

Additional application manifests can be added here following the same pattern.

## Application Manifest Structure

Each application manifest follows this structure:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: <app-name>
  namespace: argocd
spec:
  project: default
  destination:
    namespace: <target-namespace>
    server: https://kubernetes.default.svc
  sources:
    # Helm chart from public repository
    - repoURL: https://<helm-repo-url>
      targetRevision: <chart-version>
      chart: <chart-name>
      helm:
        valueFiles:
          - $values/k8s/<app-dir>/values.yaml
    # Values from Git repository
    - repoURL: git@github.com/wortmanb/homelab.git
      path: k8s/<app-dir>
      targetRevision: main
      ref: values
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
    automated:
      prune: true      # Delete resources removed from Git
      selfHeal: true   # Revert manual changes
```

## Adding New Applications

1. Create a values file in the appropriate directory under `/Users/bret/git/homelab/k8s/<app-name>/`
2. Create an Application manifest in this directory
3. Commit and push to Git
4. ArgoCD will automatically sync the new application (if automated sync is enabled)

## Manual Application Management

### View Application Status

```bash
argocd app list
argocd app get <app-name>
```

### Sync Application

```bash
argocd app sync <app-name>
```

### Delete Application

```bash
argocd app delete <app-name> --cascade
```

## Sync Order

Some applications have dependencies. Deploy in this order:

1. **democratic-csi**: Storage classes (required by apps needing persistent storage)
2. **metallb**: LoadBalancer IPs (required by Traefik and ArgoCD)
3. **cert-manager-config**: Certificate issuers (required by apps needing TLS)
4. **traefik**: Ingress controller (required by apps needing ingress)
5. **Applications**: Deploy application workloads

ArgoCD will handle dependencies automatically if sync waves are configured.

## Troubleshooting

### Application Stuck in Syncing

```bash
# Check application details
argocd app get <app-name>

# View application logs
kubectl logs -n argocd deployment/argocd-application-controller
```

### Application OutOfSync

```bash
# View differences
argocd app diff <app-name>

# Force sync
argocd app sync <app-name> --force
```

### Helm Chart Not Found

Verify the Helm repository is added to ArgoCD:
```bash
argocd repo list
```

Add missing repository:
```bash
argocd repo add <helm-repo-url> --type helm --name <repo-name>
```
