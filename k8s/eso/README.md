# External Secrets Setup

This directory contains the External Secrets Operator configuration for syncing secrets from Vault to Kubernetes.

## Prerequisites

1. Vault must be unsealed and accessible at `https://192.168.10.101:8200`
2. Vault Kubernetes auth must be configured (see below)

## Vault Configuration

Run these commands to configure Vault for Kubernetes authentication:

```bash
# 1. Unseal Vault first if needed
vault operator unseal

# 2. Enable Kubernetes auth (if not already enabled)
vault auth enable kubernetes

# 3. Get the Kubernetes API server CA and token
# Run these on a machine with kubectl access
export K8S_HOST="https://192.168.10.21:6443"  # Your K8s API server
export SA_TOKEN=$(kubectl create token external-secrets-vault -n external-secrets --duration=8760h)
export K8S_CA_CERT=$(kubectl config view --raw --minify --flatten -o jsonpath='{.clusters[].cluster.certificate-authority-data}' | base64 -d)

# 4. Configure Vault Kubernetes auth
vault write auth/kubernetes/config \
    kubernetes_host="$K8S_HOST" \
    kubernetes_ca_cert="$K8S_CA_CERT" \
    disable_local_ca_jwt=true

# 5. Create a policy for external-secrets
vault policy write external-secrets - <<EOF
path "secret/data/*" {
  capabilities = ["read", "list"]
}
path "secret/metadata/*" {
  capabilities = ["read", "list"]
}
EOF

# 6. Create a role for external-secrets
vault write auth/kubernetes/role/external-secrets \
    bound_service_account_names=external-secrets-vault \
    bound_service_account_namespaces=external-secrets \
    policies=external-secrets \
    ttl=1h
```

## Vault CA Certificate

If Vault uses a self-signed certificate, create a ConfigMap with the CA:

```bash
# Get the CA cert from Vault server and create ConfigMap
kubectl create configmap vault-ca \
    --from-file=ca.crt=/path/to/vault-ca.crt \
    -n external-secrets
```

Or if Vault uses a trusted CA, update `cluster-secret-store.yaml` to remove the caProvider section.

## Testing

After setup, verify the ClusterSecretStore is ready:

```bash
kubectl get clustersecretstore vault-backend
```

Should show `Ready: True`.
