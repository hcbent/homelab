# Secret Migration to Vault - Commands to Run

This document contains the commands you need to run to migrate all remaining hardcoded secrets to Vault.

## Prerequisites

```bash
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY=true
vault login  # Use your root token
```

## Task 2.6: Migrate Home Assistant and Pi-hole Credentials

### Pi-hole Credentials
```bash
# Current value: ***REMOVED*** (base64: ***REMOVED***)
vault kv put secret/homelab/pihole/lab/credentials \
  webpassword="***REMOVED***"

# Verify
vault kv get secret/homelab/pihole/lab/credentials
```

### Home Assistant Credentials
```bash
# Home Assistant uses Helm values and doesn't have hardcoded credentials
# If you need to store any HA credentials, use:
# vault kv put secret/homelab/home-assistant/lab/credentials \
#   api_token="your-token-here" \
#   admin_password="your-password"
```

## Task 2.7: Migrate Database Passwords and API Tokens

### Paperless Database Credentials
```bash
vault kv put secret/homelab/databases/paperless \
  database="paperless" \
  user="paperless" \
  password="paperless" \
  root_password="paperless" \
  secret_key="***REMOVED***C8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0rC8lP6sB3fE1oD7aT4hW9mX2nL5vY0qR8jF6cU3zA1dT7eM4iN9yQ2wK5tV0r" \
  admin_password="admin"

# Verify
vault kv get secret/homelab/databases/paperless
```

### Cerebro Elasticsearch Credentials
```bash
vault kv put secret/homelab/elasticsearch/cerebro \
  password="***REMOVED***"

# Verify
vault kv get secret/homelab/elasticsearch/cerebro
```

### Prometheus Credentials
```bash
vault kv put secret/homelab/prometheus/lab/credentials \
  admin_password="***REMOVED***"

# Verify
vault kv get secret/homelab/prometheus/lab/credentials
```

### Unpackerr API Keys
```bash
vault kv put secret/homelab/apps/unpackerr \
  sonarr_api_key="***REMOVED***" \
  radarr_api_key="***REMOVED***"

# Verify
vault kv get secret/homelab/apps/unpackerr
```

### Lidarr API Key
```bash
# The current value is placeholder "CHANGE_ME_LIDARR_API_KEY"
# Replace with your actual API key
vault kv put secret/homelab/apps/lidarr \
  api_key="YOUR_ACTUAL_LIDARR_API_KEY"

# Verify
vault kv get secret/homelab/apps/lidarr
```

## Verification

Run these commands to verify all secrets are stored:

```bash
echo "=== Verifying all migrated secrets ==="
echo ""
echo "Pi-hole:"
vault kv get -field=webpassword secret/homelab/pihole/lab/credentials
echo ""
echo "Paperless DB:"
vault kv get -field=password secret/homelab/databases/paperless
echo ""
echo "Cerebro:"
vault kv get -field=password secret/homelab/elasticsearch/cerebro
echo ""
echo "Prometheus:"
vault kv get -field=admin_password secret/homelab/prometheus/lab/credentials
echo ""
echo "Unpackerr:"
vault kv get -field=sonarr_api_key secret/homelab/apps/unpackerr
echo ""
echo "All secrets migrated successfully!"
```

## Files to Clean Up After Migration

After migrating these secrets, the following files will be updated to remove hardcoded credentials:

1. `/Users/bret/git/homelab/k8s/pihole/pihole.yaml`
2. `/Users/bret/git/homelab/k8s/home-apps/paperless/db-deployment.yaml`
3. `/Users/bret/git/homelab/k8s/home-apps/paperless/docker-compose-env-configmap.yaml`
4. `/Users/bret/git/homelab/k8s/cerebro/cerebro.yaml`
5. `/Users/bret/git/homelab/k8s/paperless/paperless.yaml`
6. `/Users/bret/git/homelab/k8s/freenas-storageclass.yaml`
7. `/Users/bret/git/homelab/k8s/prometheus/prometheus.yaml`
8. `/Users/bret/git/homelab/k8s/helm/values/freenas-nfs.yaml`
9. `/Users/bret/git/homelab/k8s/helm/values/prometheus.yaml`
10. `/Users/bret/git/homelab/k8s/helm/values/freenas-iscsi.yaml`
11. `/Users/bret/git/homelab/docker/elastic/cerebro/config/application.conf`
12. `/Users/bret/git/homelab/docker/home-apps/docker-compose.yml`
13. `/Users/bret/git/homelab/docker/docker-compose.yml`
14. `/Users/bret/git/homelab/ansible/host_vars/lidarr/vault.yml`

These will be replaced with placeholders and Vault references.
