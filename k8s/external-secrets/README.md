# External Secrets Operator Configuration

This directory contains the configuration for External Secrets Operator (ESO) in the homelab Kubernetes cluster.

## Files

- `values.yaml` - Helm values for the External Secrets Operator chart
- `vault-secret-store.yaml` - ClusterSecretStore configuration for Vault backend
- `external-secret.example.yaml` - Example ExternalSecret resources for reference

## Quick Start

### 1. Deploy ESO via ArgoCD

```bash
kubectl apply -f ../external-secrets-app.yaml
```

### 2. Create Vault Token Secret

```bash
# Get a Vault token with appropriate permissions
export VAULT_ADDR="https://192.168.10.101:8200"
vault token create -policy=apps -ttl=8760h

# Create the Kubernetes secret
kubectl create secret generic vault-token \
  -n external-secrets-system \
  --from-literal=token="<your-vault-token>"
```

### 3. Apply ClusterSecretStore

```bash
kubectl apply -f vault-secret-store.yaml
```

### 4. Verify Setup

```bash
# Check ESO is running
kubectl get pods -n external-secrets-system

# Check ClusterSecretStore is ready
kubectl get clustersecretstore vault-backend

# Expected output:
# NAME            AGE   STATUS   CAPABILITIES   READY
# vault-backend   10s   Valid    ReadWrite      True
```

## Usage

To create a new ExternalSecret for your application:

1. Store your secret in Vault:
   ```bash
   vault kv put secret/homelab/myapp/credentials \
       username=myuser \
       password=mypassword
   ```

2. Create an ExternalSecret resource (see `external-secret.example.yaml`):
   ```yaml
   apiVersion: external-secrets.io/v1beta1
   kind: ExternalSecret
   metadata:
     name: myapp-secret
     namespace: myapp
   spec:
     refreshInterval: 1h
     secretStoreRef:
       name: vault-backend
       kind: ClusterSecretStore
     target:
       name: myapp-secret
     dataFrom:
       - extract:
           key: homelab/myapp/credentials
   ```

3. Apply the ExternalSecret:
   ```bash
   kubectl apply -f myapp-external-secret.yaml
   ```

4. Use the secret in your application:
   ```yaml
   env:
   - name: USERNAME
     valueFrom:
       secretKeyRef:
         name: myapp-secret
         key: username
   ```

## Documentation

See [docs/EXTERNAL-SECRETS-SETUP.md](../../docs/EXTERNAL-SECRETS-SETUP.md) for comprehensive documentation including:
- Architecture overview
- Installation steps
- Troubleshooting guide
- Security best practices
- Secret rotation procedures

## Existing ExternalSecrets

The following ExternalSecrets are configured in the cluster:

| Service | ExternalSecret Location | Vault Path | Namespace |
|---------|------------------------|------------|-----------|
| Pi-hole | `k8s/pihole/external-secret.yaml` | `secret/homelab/pihole/lab/credentials` | `pihole` |
| Paperless | `k8s/paperless/external-secret.yaml` | `secret/homelab/databases/paperless` | `default` |
| Cerebro | `k8s/cerebro/external-secret.yaml` | `secret/homelab/elasticsearch/cerebro` | `elastic-stack` |
| Prometheus | `k8s/prometheus/external-secret.yaml` | `secret/homelab/prometheus/lab/credentials` | `prometheus` |
| Democratic CSI | `k8s/freenas/external-secret.yaml` | `secret/homelab/freenas/credentials` | `democratic-csi` |
| Unpackerr | `k8s/unpackerr/external-secret.yaml` | `secret/homelab/apps/{radarr,sonarr}` | `default` |

## Troubleshooting

### ExternalSecret not syncing

```bash
# Check ExternalSecret status
kubectl describe externalsecret <name> -n <namespace>

# Check ESO logs
kubectl logs -n external-secrets-system deployment/external-secrets
```

### Secret not found in Vault

```bash
# Verify the secret exists in Vault
vault kv get secret/homelab/path/to/secret

# Check the path matches the ExternalSecret configuration
```

### TLS/Connection issues

```bash
# Test Vault connectivity from the cluster
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl -k https://192.168.10.101:8200/v1/sys/health
```

## References

- [External Secrets Operator Documentation](https://external-secrets.io/)
- [API Reference](https://external-secrets.io/latest/api/externalsecret/)
- [Vault Provider](https://external-secrets.io/latest/provider/hashicorp-vault/)
