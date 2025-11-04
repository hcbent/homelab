# External Secrets Operator - Quick Reference

## Quick Commands

### Check ESO Status
```bash
# Pods running?
kubectl get pods -n external-secrets-system

# SecretStore ready?
kubectl get clustersecretstore vault-backend

# All ExternalSecrets synced?
kubectl get externalsecret -A
```

### Deploy ESO
```bash
kubectl apply -f k8s/external-secrets-app.yaml
kubectl create secret generic vault-token -n external-secrets-system --from-literal=token="<token>"
kubectl apply -f k8s/external-secrets/vault-secret-store.yaml
```

### Create New ExternalSecret
```bash
# 1. Add to Vault
vault kv put secret/homelab/myapp/creds password=secret123

# 2. Create ExternalSecret
cat <<EOF | kubectl apply -f -
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: myapp-secret
  namespace: default
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: myapp-secret
  dataFrom:
    - extract:
        key: homelab/myapp/creds
EOF

# 3. Verify
kubectl get externalsecret myapp-secret
kubectl get secret myapp-secret
```

### Force Secret Refresh
```bash
kubectl annotate externalsecret <name> -n <namespace> force-sync=$(date +%s) --overwrite
```

### Troubleshooting
```bash
# Check ExternalSecret status
kubectl describe externalsecret <name> -n <namespace>

# Check ESO logs
kubectl logs -n external-secrets-system deployment/external-secrets --tail=50

# Test Vault from cluster
kubectl run vault-test --rm -it --restart=Never --image=vault:latest -- \
  vault status -address=https://192.168.10.101:8200 -tls-skip-verify

# Verify secret exists in Vault
vault kv get secret/homelab/path/to/secret
```

## ExternalSecret Locations

| Service | File | Namespace |
|---------|------|-----------|
| Pi-hole | `k8s/pihole/external-secret.yaml` | `pihole` |
| Paperless | `k8s/paperless/external-secret.yaml` | `default` |
| Cerebro | `k8s/cerebro/external-secret.yaml` | `elastic-stack` |
| Prometheus | `k8s/prometheus/external-secret.yaml` | `prometheus` |
| Democratic CSI | `k8s/freenas/external-secret.yaml` | `democratic-csi` |
| Unpackerr | `k8s/unpackerr/external-secret.yaml` | `default` |

## Vault Paths

| Service | Vault Path |
|---------|-----------|
| Pi-hole | `secret/homelab/pihole/lab/credentials` |
| Paperless | `secret/homelab/databases/paperless` |
| Cerebro | `secret/homelab/elasticsearch/cerebro` |
| Prometheus | `secret/homelab/prometheus/lab/credentials` |
| TrueNAS | `secret/homelab/freenas/credentials` |
| Radarr | `secret/homelab/apps/radarr` |
| Sonarr | `secret/homelab/apps/sonarr` |

## Common Issues

### ExternalSecret not syncing
```bash
# Check the ExternalSecret
kubectl describe externalsecret <name> -n <namespace>

# Look for errors in Events section
# Common causes:
# - Secret path doesn't exist in Vault
# - Token lacks permissions
# - Network connectivity issue
```

### SecretStore not ready
```bash
# Check status
kubectl describe clustersecretstore vault-backend

# Verify Vault token
kubectl get secret vault-token -n external-secrets-system -o jsonpath='{.data.token}' | base64 -d

# Test token
export VAULT_TOKEN="<token-from-above>"
vault token lookup
```

### Secret not appearing in pod
```bash
# Verify secret exists
kubectl get secret <name> -n <namespace>

# Check pod env
kubectl describe pod <pod-name> -n <namespace> | grep -A10 Environment

# Restart pod
kubectl delete pod <pod-name> -n <namespace>
```

## Using Secrets in Pods

### As environment variables
```yaml
env:
- name: PASSWORD
  valueFrom:
    secretKeyRef:
      name: myapp-secret
      key: password
```

### As volume mount
```yaml
volumeMounts:
- name: secrets
  mountPath: /etc/secrets
volumes:
- name: secrets
  secret:
    secretName: myapp-secret
```

### All keys as env vars
```yaml
envFrom:
- secretRef:
    name: myapp-secret
```

## Monitoring

```bash
# Port-forward metrics
kubectl port-forward -n external-secrets-system deployment/external-secrets 8080:8080

# View metrics
curl localhost:8080/metrics | grep externalsecret

# Key metrics:
# - externalsecret_status_condition
# - externalsecret_sync_calls_total
# - externalsecret_sync_calls_error
```

## Secret Rotation

```bash
# 1. Update in Vault
vault kv put secret/homelab/myapp/creds password=newpassword

# 2. Force sync (optional, otherwise wait 1h)
kubectl annotate externalsecret myapp-secret -n default force-sync=$(date +%s) --overwrite

# 3. Restart app
kubectl rollout restart deployment/myapp -n default
```

## Useful Aliases

Add to `~/.bashrc` or `~/.zshrc`:

```bash
alias k='kubectl'
alias kgex='kubectl get externalsecret -A'
alias kdes='kubectl describe externalsecret'
alias kgss='kubectl get clustersecretstore'
alias kesologs='kubectl logs -n external-secrets-system deployment/external-secrets'
alias kforcesync='kubectl annotate externalsecret $1 -n $2 force-sync=$(date +%s) --overwrite'
```

## Documentation

- **Setup Guide**: [docs/EXTERNAL-SECRETS-SETUP.md](./EXTERNAL-SECRETS-SETUP.md)
- **Deployment Guide**: [docs/EXTERNAL-SECRETS-DEPLOYMENT.md](./EXTERNAL-SECRETS-DEPLOYMENT.md)
- **Implementation Summary**: [EXTERNAL-SECRETS-IMPLEMENTATION.md](../EXTERNAL-SECRETS-IMPLEMENTATION.md)
- **Example Files**: [k8s/external-secrets/](../k8s/external-secrets/)

## Emergency Contacts

- ESO GitHub: https://github.com/external-secrets/external-secrets
- ESO Docs: https://external-secrets.io/
- Vault Docs: https://developer.hashicorp.com/vault

## Health Check Commands

```bash
# Quick health check script
check_eso_health() {
  echo "=== ESO Pods ==="
  kubectl get pods -n external-secrets-system

  echo -e "\n=== ClusterSecretStore ==="
  kubectl get clustersecretstore vault-backend

  echo -e "\n=== ExternalSecrets ==="
  kubectl get externalsecret -A

  echo -e "\n=== Recent ESO Logs ==="
  kubectl logs -n external-secrets-system deployment/external-secrets --tail=5
}

# Run it
check_eso_health
```

Copy this function to your shell profile for easy access!
