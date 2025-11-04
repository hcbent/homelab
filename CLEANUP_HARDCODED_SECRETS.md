# Cleanup Plan for Hardcoded Secrets

This document outlines all files with hardcoded secrets and the actions needed to clean them up.

## Prerequisites

1. **FIRST**: Run all commands in `MIGRATE_SECRETS_TO_VAULT.md` to migrate secrets to Vault
2. **THEN**: Follow the cleanup steps below

## Files with Hardcoded Secrets

### Category 1: Kubernetes Manifests (k8s/)

#### 1. /Users/bret/git/homelab/k8s/pihole/pihole.yaml
- **Secret**: WEBPASSWORD: ***REMOVED*** (base64 for "***REMOVED***")
- **Action**: Replace with placeholder or use External Secrets Operator
- **Example file created**: k8s/pihole/pihole.yaml.example
- **Vault path**: secret/homelab/pihole/lab/credentials:webpassword

#### 2. /Users/bret/git/homelab/k8s/paperless/paperless.yaml
- **Secrets**: Multiple database passwords
  - adminPassword: "***REMOVED***"
  - password: paperless (multiple instances)
  - postgresPassword: "postgres"
- **Action**: Replace with Vault references or External Secrets
- **Vault path**: secret/homelab/databases/paperless

#### 3. /Users/bret/git/homelab/k8s/cerebro/cerebro.yaml
- **Secret**: password = "***REMOVED***"
- **Action**: Replace with placeholder
- **Vault path**: secret/homelab/elasticsearch/cerebro:password

#### 4. /Users/bret/git/homelab/k8s/freenas-storageclass.yaml
- **Secret**: password: ***REMOVED***
- **Action**: Replace with placeholder (already handled in task 2.3)
- **Vault path**: secret/homelab/freenas/credentials

#### 5. /Users/bret/git/homelab/k8s/prometheus/prometheus.yaml
- **Secret**: adminPassword: ***REMOVED***
- **Action**: Replace with Vault reference
- **Vault path**: secret/homelab/prometheus/lab/credentials:admin_password

#### 6. /Users/bret/git/homelab/k8s/helm/values/freenas-nfs.yaml
- **Secret**: password: "***REMOVED***" (commented and uncommented versions)
- **Action**: Already has .example file, remove uncommented password
- **Vault path**: secret/homelab/freenas/credentials

#### 7. /Users/bret/git/homelab/k8s/helm/values/prometheus.yaml
- **Secret**: adminPassword: ***REMOVED***
- **Action**: Replace with VAULT_SECRET_REFERENCE
- **Vault path**: secret/homelab/prometheus/lab/credentials:admin_password

#### 8. /Users/bret/git/homelab/k8s/helm/values/freenas-iscsi.yaml
- **Secret**: password: ***REMOVED***
- **Action**: Already has .example file, update to use placeholder
- **Vault path**: secret/homelab/freenas/credentials

#### 9. /Users/bret/git/homelab/k8s/home-apps/paperless/db-deployment.yaml
- **Secrets**: MARIADB_PASSWORD, MARIADB_ROOT_PASSWORD
- **Action**: Replace with placeholders or Secret references
- **Vault path**: secret/homelab/databases/paperless

#### 10. /Users/bret/git/homelab/k8s/home-apps/paperless/docker-compose-env-configmap.yaml
- **Secret**: PAPERLESS_SECRET_KEY (very long key)
- **Action**: Replace with placeholder
- **Vault path**: secret/homelab/databases/paperless:secret_key

### Category 2: Docker Compose Files (docker/)

#### 11. /Users/bret/git/homelab/docker/elastic/cerebro/config/application.conf
- **Secrets**: password = "***REMOVED***" (appears 3 times)
- **Action**: Create .example file with placeholders
- **Vault path**: secret/homelab/elasticsearch/cerebro:password

#### 12. /Users/bret/git/homelab/docker/home-apps/docker-compose.yml
- **Secrets**:
  - POSTGRES_PASSWORD: paperless
  - PAPERLESS_ADMIN_PASSWORD: admin
- **Action**: Create .example file
- **Vault path**: secret/homelab/databases/paperless

#### 13. /Users/bret/git/homelab/docker/docker-compose.yml
- **Secrets**:
  - UN_SONARR_0_API_KEY=***REMOVED***
  - UN_RADARR_0_API_KEY=***REMOVED***
- **Action**: Create .example file
- **Vault path**: secret/homelab/apps/unpackerr

### Category 3: Ansible Files

#### 14. /Users/bret/git/homelab/ansible/playbooks/deploy_pihole.yml
- **Secret**: pihole_webpassword: "***REMOVED***"
- **Action**: Update to use Vault lookup
- **Example file created**: ansible/playbooks/deploy_pihole.yml.example
- **Vault path**: secret/homelab/pihole/lab/credentials:webpassword

#### 15. /Users/bret/git/homelab/ansible/host_vars/lidarr/vault.yml
- **Secret**: api_key: "CHANGE_ME_LIDARR_API_KEY"
- **Action**: This is already a placeholder, just document Vault path
- **Vault path**: secret/homelab/apps/lidarr:api_key

## Cleanup Script

```bash
#!/bin/bash
# Run this script AFTER migrating all secrets to Vault

set -e

echo "=== Cleaning up hardcoded secrets ==="
echo ""
echo "WARNING: This will modify files in place!"
echo "Make sure you have:"
echo "  1. Migrated all secrets to Vault (see MIGRATE_SECRETS_TO_VAULT.md)"
echo "  2. Committed your current state to git"
echo "  3. Backed up any files you want to preserve"
echo ""
read -p "Continue? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
  echo "Aborted."
  exit 1
fi

# Note: The actual cleanup would involve either:
# 1. Manually editing each file to replace secrets with placeholders
# 2. Using External Secrets Operator in Kubernetes
# 3. Using Vault Agent Injector
# 4. Or documenting that files should be generated from .example templates

echo ""
echo "Cleanup tasks:"
echo "1. Update Ansible playbooks to use Vault lookups (see ansible/vault-integration-example.yml)"
echo "2. For Kubernetes secrets, consider using External Secrets Operator"
echo "3. For docker-compose files, use environment variables from Vault"
echo "4. Replace hardcoded values with VAULT_SECRET_REFERENCE placeholders"
echo ""
echo "See the file list above for specific files to update."
```

## Recommended Approach for Kubernetes

Instead of manual secret management, consider using **External Secrets Operator**:

1. Install External Secrets Operator:
```bash
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets --create-namespace
```

2. Create a SecretStore pointing to your Vault:
```yaml
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: vault-backend
  namespace: default
spec:
  provider:
    vault:
      server: "https://vault.lab.thewortmans.org:8200"
      path: "secret"
      version: "v2"
      auth:
        tokenSecretRef:
          name: "vault-token"
          key: "token"
```

3. Create ExternalSecret resources for each secret:
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: pihole-secret
  namespace: pihole
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: pihole-secret
    creationPolicy: Owner
  data:
    - secretKey: WEBPASSWORD
      remoteRef:
        key: homelab/pihole/lab/credentials
        property: webpassword
```

This way, secrets are automatically synced from Vault to Kubernetes, and you don't need to manually manage them.

## Ansible Vault Integration Pattern

For Ansible playbooks, use this pattern:

```yaml
---
- name: Your Playbook
  hosts: all

  environment:
    VAULT_ADDR: "https://vault.lab.thewortmans.org:8200"
    VAULT_TOKEN: "{{ lookup('env', 'VAULT_TOKEN') }}"
    VAULT_SKIP_VERIFY: "true"

  vars:
    my_secret: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/path/to/secret:key') }}"

  tasks:
    - name: Use secret
      debug:
        msg: "Secret retrieved from Vault"
      no_log: true
```

## Verification After Cleanup

Run this comprehensive grep to verify no secrets remain:

```bash
# Check for common patterns
grep -r -i "***REMOVED***" --include="*.yml" --include="*.yaml" --include="*.tf" \
  --exclude-dir=".git" --exclude="*.example" .

grep -r "***REMOVED***" --include="*.yml" --include="*.yaml" \
  --exclude-dir=".git" --exclude="*.example" .

grep -r "***REMOVED***\|***REMOVED***" \
  --include="*.yml" --include="*.yaml" --exclude-dir=".git" --exclude="*.example" .

# Check for base64 encoded "***REMOVED***"
grep -r "***REMOVED***" --include="*.yml" --include="*.yaml" \
  --exclude-dir=".git" --exclude="*.example" .

# Check for generic password patterns
grep -r -E "password\s*[:=]\s*['\"]?[a-zA-Z0-9]{6,}" --include="*.yml" --include="*.yaml" \
  --exclude-dir=".git" --exclude="*.example" . | \
  grep -v "VAULT\|example\|placeholder\|your-\|REPLACE"
```

## Next Steps

1. Run the Vault migration commands from MIGRATE_SECRETS_TO_VAULT.md
2. Update files to use Vault references or External Secrets Operator
3. Create .example files for all files with secrets
4. Test that applications can retrieve secrets from Vault
5. Run verification grep commands
6. Commit the cleaned-up code
