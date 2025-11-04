# External Secrets Operator Setup Guide

## Overview

This guide documents the setup and configuration of External Secrets Operator (ESO) in the homelab Kubernetes cluster. ESO automates the synchronization of secrets from HashiCorp Vault to Kubernetes Secret objects, eliminating the need for manual secret management.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              Kubernetes Cluster                     │
│                                                     │
│  ┌──────────────────────────────────────────┐     │
│  │  External Secrets Operator               │     │
│  │  (external-secrets-system namespace)     │     │
│  └────────────┬─────────────────────────────┘     │
│               │                                    │
│               │ Watches ExternalSecret CRDs       │
│               ▼                                    │
│  ┌──────────────────────────────────────────┐     │
│  │  ExternalSecret Resources                │     │
│  │  - pihole-secret                         │     │
│  │  - paperless-db-secret                   │     │
│  │  - cerebro-secret                        │     │
│  │  - prometheus-grafana-secret             │     │
│  │  - freenas-credentials                   │     │
│  │  - unpackerr-secret                      │     │
│  └────────────┬─────────────────────────────┘     │
│               │                                    │
│               │ Creates/Updates                    │
│               ▼                                    │
│  ┌──────────────────────────────────────────┐     │
│  │  Kubernetes Secrets                      │     │
│  │  (Auto-generated and managed by ESO)     │     │
│  └──────────────────────────────────────────┘     │
│                                                     │
└────────────┬────────────────────────────────────────┘
             │
             │ Authenticates and Fetches Secrets
             ▼
┌─────────────────────────────────────────────────────┐
│     HashiCorp Vault (192.168.10.101:8200)          │
│                                                     │
│     secret/homelab/*                                │
│     ├── pihole/lab/credentials                     │
│     ├── databases/paperless                        │
│     ├── elasticsearch/cerebro                      │
│     ├── prometheus/lab/credentials                 │
│     ├── freenas/credentials                        │
│     ├── apps/radarr                                │
│     └── apps/sonarr                                │
└─────────────────────────────────────────────────────┘
```

## Components

### 1. External Secrets Operator
- **Namespace**: `external-secrets-system`
- **Deployed via**: ArgoCD Application (`k8s/external-secrets-app.yaml`)
- **Helm Chart**: https://charts.external-secrets.io
- **Version**: 0.10.0

### 2. ClusterSecretStore
- **Name**: `vault-backend`
- **Type**: ClusterSecretStore (available to all namespaces)
- **Backend**: HashiCorp Vault at https://192.168.10.101:8200
- **Auth Method**: Token-based (for initial setup)

### 3. ExternalSecret Resources
ExternalSecret CRDs that define which secrets to sync from Vault:
- `k8s/pihole/external-secret.yaml` - Pi-hole web password
- `k8s/paperless/external-secret.yaml` - Paperless DB credentials
- `k8s/cerebro/external-secret.yaml` - Cerebro Elasticsearch password
- `k8s/prometheus/external-secret.yaml` - Grafana admin password
- `k8s/freenas/external-secret.yaml` - TrueNAS credentials
- `k8s/unpackerr/external-secret.yaml` - Radarr and Sonarr API keys

## Installation

### Prerequisites

1. **Vault is accessible** from the Kubernetes cluster:
   ```bash
   # Test connectivity from a pod
   kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
     curl -k https://192.168.10.101:8200/v1/sys/health
   ```

2. **Vault token with appropriate permissions**:
   - Create a token with the `apps` policy or similar
   - Store the token securely for the next step

### Step 1: Deploy External Secrets Operator via ArgoCD

```bash
# Apply the ArgoCD application
kubectl apply -f k8s/external-secrets-app.yaml

# Wait for ESO to be ready
kubectl wait --for=condition=available --timeout=300s \
  deployment/external-secrets -n external-secrets-system
kubectl wait --for=condition=available --timeout=300s \
  deployment/external-secrets-webhook -n external-secrets-system
```

### Step 2: Create Vault Token Secret

Before applying the ClusterSecretStore, create the Vault token secret:

```bash
# Generate or obtain a Vault token with appropriate permissions
# Example: Create a token with the 'apps' policy
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_TOKEN="<your-admin-token>"

# Create a token for ESO with the apps policy
vault token create -policy=apps -ttl=8760h -display-name="k8s-eso"

# Create the Kubernetes secret with the token
kubectl create secret generic vault-token \
  -n external-secrets-system \
  --from-literal=token="<token-from-previous-command>"
```

### Step 3: Apply ClusterSecretStore

```bash
# Apply the Vault SecretStore configuration
kubectl apply -f k8s/external-secrets/vault-secret-store.yaml

# Verify the SecretStore is ready
kubectl get clustersecretstore vault-backend
```

Expected output:
```
NAME            AGE   STATUS   CAPABILITIES   READY
vault-backend   10s   Valid    ReadWrite      True
```

### Step 4: Deploy ExternalSecret Resources

Deploy ExternalSecrets for each service:

```bash
# Pi-hole
kubectl apply -f k8s/pihole/external-secret.yaml

# Paperless
kubectl apply -f k8s/paperless/external-secret.yaml

# Cerebro
kubectl apply -f k8s/cerebro/external-secret.yaml

# Prometheus/Grafana
kubectl apply -f k8s/prometheus/external-secret.yaml

# FreeNAS/Democratic CSI
kubectl apply -f k8s/freenas/external-secret.yaml

# Unpackerr
kubectl apply -f k8s/unpackerr/external-secret.yaml
```

### Step 5: Verify Secret Synchronization

Check that secrets are created and synced:

```bash
# Check ExternalSecret status
kubectl get externalsecret -A

# Check specific secret
kubectl get secret pihole-secret -n pihole -o yaml

# Describe an ExternalSecret for detailed status
kubectl describe externalsecret pihole-secret -n pihole
```

Expected status:
```
Status:
  Conditions:
    Last Transition Time:  2024-11-04T...
    Message:               Secret was synced
    Reason:                SecretSynced
    Status:                True
    Type:                  Ready
  Refresh Time:           2024-11-04T...
  Synced Resource Version: 1-xxxxx
```

## Configuration Details

### Vault Path Structure

All secrets are stored under the `secret/homelab/` path in Vault:

```
secret/homelab/
├── pihole/lab/credentials
│   └── webpassword
├── databases/paperless
│   ├── admin_password
│   ├── db_password
│   ├── db_user
│   └── db_name
├── elasticsearch/cerebro
│   └── password
├── prometheus/lab/credentials
│   └── admin_password
├── freenas/credentials
│   ├── password
│   ├── api_key
│   └── ssh_password
├── apps/radarr
│   └── api_key
└── apps/sonarr
    └── api_key
```

### Secret Refresh Intervals

All ExternalSecrets are configured with a 1-hour refresh interval:
```yaml
spec:
  refreshInterval: 1h
```

This means ESO will check Vault every hour for secret updates and sync changes to Kubernetes.

### Authentication Methods

#### Current: Token Authentication (Simple)
- Uses a long-lived token stored in `vault-token` secret
- Suitable for initial setup and testing
- Token should have minimal required permissions (apps policy)

#### Recommended: Kubernetes Authentication (Production)

For production use, configure Vault's Kubernetes auth method:

1. **Enable Kubernetes auth in Vault**:
```bash
vault auth enable kubernetes

vault write auth/kubernetes/config \
    kubernetes_host="https://<kubernetes-api-server>:6443" \
    kubernetes_ca_cert=@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt \
    token_reviewer_jwt=@/var/run/secrets/kubernetes.io/serviceaccount/token
```

2. **Create a role for ESO**:
```bash
vault write auth/kubernetes/role/external-secrets \
    bound_service_account_names=external-secrets \
    bound_service_account_namespaces=external-secrets-system \
    policies=apps \
    ttl=1h
```

3. **Update ClusterSecretStore**:
```yaml
spec:
  provider:
    vault:
      server: "https://192.168.10.101:8200"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "external-secrets"
          serviceAccountRef:
            name: "external-secrets"
```

## Adding New Secrets

### 1. Store Secret in Vault

```bash
# Set Vault address and authenticate
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_TOKEN="<your-token>"

# Store a new secret
vault kv put secret/homelab/myapp/credentials \
    username=myuser \
    password=mypassword
```

### 2. Create ExternalSecret Resource

Create a file `k8s/myapp/external-secret.yaml`:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: myapp-secret
  namespace: myapp-namespace
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: myapp-secret
    creationPolicy: Owner
    template:
      type: Opaque
      data:
        username: "{{ .username }}"
        password: "{{ .password }}"
  dataFrom:
    - extract:
        key: homelab/myapp/credentials
```

### 3. Apply the ExternalSecret

```bash
kubectl apply -f k8s/myapp/external-secret.yaml

# Verify
kubectl get externalsecret myapp-secret -n myapp-namespace
kubectl get secret myapp-secret -n myapp-namespace
```

### 4. Use the Secret in Your Application

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  template:
    spec:
      containers:
      - name: myapp
        env:
        - name: USERNAME
          valueFrom:
            secretKeyRef:
              name: myapp-secret
              key: username
        - name: PASSWORD
          valueFrom:
            secretKeyRef:
              name: myapp-secret
              key: password
```

## Troubleshooting

### ExternalSecret not syncing

1. **Check ExternalSecret status**:
```bash
kubectl describe externalsecret <name> -n <namespace>
```

Look for error messages in the Events section.

2. **Check ESO logs**:
```bash
kubectl logs -n external-secrets-system deployment/external-secrets
```

3. **Verify Vault connectivity**:
```bash
# From a pod in the cluster
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl -k -H "X-Vault-Token: <token>" \
  https://192.168.10.101:8200/v1/secret/data/homelab/pihole/lab/credentials
```

### ClusterSecretStore not ready

1. **Check SecretStore status**:
```bash
kubectl describe clustersecretstore vault-backend
```

2. **Verify Vault token secret exists**:
```bash
kubectl get secret vault-token -n external-secrets-system
```

3. **Test Vault token**:
```bash
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_TOKEN="<token-from-secret>"
vault token lookup
```

### Secret not appearing in pod

1. **Verify secret exists**:
```bash
kubectl get secret <secret-name> -n <namespace>
```

2. **Check secret data**:
```bash
kubectl get secret <secret-name> -n <namespace> -o yaml
```

3. **Restart the pod** to pick up new secret:
```bash
kubectl rollout restart deployment/<deployment-name> -n <namespace>
```

### TLS Certificate Issues

If you encounter TLS verification errors with Vault:

**Option 1: Provide CA Certificate** (Recommended)
```yaml
spec:
  provider:
    vault:
      caBundle: "<base64-encoded-ca-cert>"
```

**Option 2: Skip TLS Verification** (Not recommended for production)
```yaml
spec:
  provider:
    vault:
      caProvider:
        type: "Secret"
        name: "vault-ca"
        namespace: "external-secrets-system"
        key: "ca.crt"
```

## Secret Rotation

ESO automatically handles secret rotation:

1. **Update secret in Vault**:
```bash
vault kv put secret/homelab/myapp/credentials password=newpassword
```

2. **Wait for refresh interval** (default: 1h) or force immediate sync:
```bash
# Force immediate reconciliation
kubectl annotate externalsecret <name> -n <namespace> \
  force-sync=$(date +%s) --overwrite
```

3. **Restart pods** to use new secret values:
```bash
kubectl rollout restart deployment/<deployment-name> -n <namespace>
```

## Monitoring

### Metrics

ESO exposes Prometheus metrics on port 8080:
```bash
# Port-forward to access metrics
kubectl port-forward -n external-secrets-system \
  deployment/external-secrets 8080:8080

# View metrics
curl http://localhost:8080/metrics
```

Key metrics:
- `externalsecret_status_condition` - Status of ExternalSecrets
- `externalsecret_sync_calls_total` - Total sync operations
- `externalsecret_sync_calls_error` - Failed sync operations

### Alerts (if using Prometheus)

Example alert rules:

```yaml
- alert: ExternalSecretSyncFailing
  expr: externalsecret_status_condition{condition="Ready",status="False"} == 1
  for: 15m
  annotations:
    summary: "ExternalSecret {{ $labels.name }} in {{ $labels.namespace }} is not syncing"

- alert: ExternalSecretStale
  expr: time() - externalsecret_sync_timestamp > 7200
  annotations:
    summary: "ExternalSecret {{ $labels.name }} hasn't synced in over 2 hours"
```

## Security Best Practices

1. **Use Kubernetes Auth Method**: Migrate from token auth to Kubernetes auth for better security
2. **Principle of Least Privilege**: Grant ESO only the Vault permissions it needs
3. **Rotate Vault Tokens**: Regularly rotate the Vault token used by ESO
4. **Namespace Isolation**: Use SecretStore (not ClusterSecretStore) for namespace-specific secrets when possible
5. **Audit Logging**: Enable Vault audit logs to track secret access
6. **TLS Verification**: Always use proper TLS certificates in production
7. **RBAC**: Restrict access to ExternalSecret and SecretStore resources

## Maintenance

### Updating ESO

```bash
# Update the chart version in k8s/external-secrets-app.yaml
# ArgoCD will automatically deploy the update

# Or manually sync
kubectl patch application external-secrets -n argocd \
  --type merge -p '{"metadata": {"annotations": {"argocd.argoproj.io/refresh": "true"}}}'
```

### Backup

ExternalSecret and SecretStore resources should be version-controlled in Git. The actual secret data is stored in Vault, which should be backed up according to Vault best practices.

```bash
# Backup Vault
vault operator raft snapshot save backup.snap

# Backup ExternalSecret definitions (already in Git)
kubectl get externalsecret -A -o yaml > externalsecrets-backup.yaml
```

## References

- [External Secrets Operator Documentation](https://external-secrets.io/)
- [Vault Kubernetes Auth Method](https://developer.hashicorp.com/vault/docs/auth/kubernetes)
- [Vault KV Secrets Engine](https://developer.hashicorp.com/vault/docs/secrets/kv)
- [Homelab Vault Setup](./VAULT-SETUP.md)

## Migration Notes

All services with `VAULT_SECRET_REFERENCE` placeholders have been migrated to use ExternalSecret resources:

- ✅ Pi-hole: Uses `pihole-secret` from Vault path `secret/homelab/pihole/lab/credentials`
- ✅ Paperless: Uses `paperless-db-secret` from Vault path `secret/homelab/databases/paperless`
- ✅ Cerebro: Uses `cerebro-secret` from Vault path `secret/homelab/elasticsearch/cerebro`
- ✅ Prometheus/Grafana: Uses `prometheus-grafana-secret` from Vault path `secret/homelab/prometheus/lab/credentials`
- ✅ Democratic CSI (TrueNAS): Uses `freenas-credentials` from Vault path `secret/homelab/freenas/credentials`
- ✅ Unpackerr: Uses `unpackerr-secret` from Vault paths `secret/homelab/apps/radarr` and `secret/homelab/apps/sonarr`

## Example Commands Reference

```bash
# List all ExternalSecrets
kubectl get externalsecret -A

# Check ESO operator logs
kubectl logs -n external-secrets-system -l app.kubernetes.io/name=external-secrets

# Check webhook logs
kubectl logs -n external-secrets-system -l app.kubernetes.io/name=external-secrets-webhook

# Validate ClusterSecretStore
kubectl get clustersecretstore vault-backend -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'

# Force secret refresh
kubectl annotate externalsecret <name> -n <namespace> force-sync=$(date +%s) --overwrite

# View all auto-generated secrets
kubectl get secret -A | grep "Opaque.*external-secrets"

# Test Vault access from cluster
kubectl run vault-test --rm -it --image=vault:latest -- \
  vault kv get -address=https://192.168.10.101:8200 secret/homelab/pihole/lab/credentials
```
