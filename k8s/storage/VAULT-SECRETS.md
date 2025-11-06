# Vault Secrets Documentation

## Overview
This document catalogs all Vault secret paths required for applications migrated from docker-compose to Kubernetes.

## Secret Paths

### Paperless-NGX Stack
**Location:** `secret/homelab/databases/paperless`

Fields required:
- `password` - PostgreSQL database password
- `secret_key` - Django secret key for Paperless-NGX
- `admin_password` - Initial admin user password

Retrieval commands:
```bash
vault kv get -field=password secret/homelab/databases/paperless
vault kv get -field=secret_key secret/homelab/databases/paperless
vault kv get -field=admin_password secret/homelab/databases/paperless
```

### Sonarr
**Location:** `secret/homelab/apps/sonarr`

Fields required:
- `api_key` - Sonarr API key for integrations

Retrieval command:
```bash
vault kv get -field=api_key secret/homelab/apps/sonarr
```

### Radarr
**Location:** `secret/homelab/apps/radarr`

Fields required:
- `api_key` - Radarr API key for integrations

Retrieval command:
```bash
vault kv get -field=api_key secret/homelab/apps/radarr
```

### Unpackerr
**Location:** `secret/homelab/apps/unpackerr`

Fields required:
- `sonarr_api_key` - Sonarr API key (references secret/homelab/apps/sonarr)
- `radarr_api_key` - Radarr API key (references secret/homelab/apps/radarr)

Retrieval commands:
```bash
vault kv get -field=sonarr_api_key secret/homelab/apps/unpackerr
vault kv get -field=radarr_api_key secret/homelab/apps/unpackerr
```

## Kubernetes Secret Creation

### Manual Secret Creation Pattern
For applications that don't use Vault integration, secrets can be created manually:

```bash
# Example: Create Paperless-NGX database secret
kubectl create secret generic paperless-db-secret \
  --from-literal=password=$(vault kv get -field=password secret/homelab/databases/paperless) \
  --from-literal=secret-key=$(vault kv get -field=secret_key secret/homelab/databases/paperless) \
  --from-literal=admin-password=$(vault kv get -field=admin_password secret/homelab/databases/paperless) \
  -n home-apps
```

### Vault Integration Notes
- This homelab uses HashiCorp Vault for centralized secret management
- Secrets should NEVER be hardcoded in Helm values files or Kubernetes manifests
- All sensitive values should be retrieved from Vault at deployment time
- See existing vault integration in `k8s/helm/values/vault.yaml` for patterns

## Vault Accessibility Test
To verify Vault is accessible and secrets are available:

```bash
# Test connection (requires VAULT_ADDR and VAULT_TOKEN environment variables)
vault status

# Test secret retrieval
vault kv list secret/homelab/apps
vault kv list secret/homelab/databases
```

## Migration Procedure
1. Ensure all secrets exist in Vault before deploying applications
2. Create Kubernetes secrets from Vault values during migration
3. Reference secrets in Helm values using secretRef or secretKeyRef
4. Validate secret retrieval in pod environment variables after deployment
