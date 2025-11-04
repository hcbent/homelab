# Secret Management Guide

This guide explains how to manage secrets using HashiCorp Vault in your homelab infrastructure.

## Table of Contents

1. [Overview](#overview)
2. [Vault Secret Organization](#vault-secret-organization)
3. [Adding Secrets](#adding-secrets)
4. [Retrieving Secrets](#retrieving-secrets)
5. [Terraform Integration](#terraform-integration)
6. [Ansible Integration](#ansible-integration)
7. [Kubernetes Integration](#kubernetes-integration)
8. [Secret Rotation](#secret-rotation)
9. [Best Practices](#best-practices)

## Overview

All secrets in this homelab infrastructure are stored in HashiCorp Vault at:
- **URL**: https://192.168.10.101:8200
- **Mount Path**: `secret/` (KV v2 engine)
- **Base Path**: `secret/homelab/`

**Zero secrets in code**: All configuration files use placeholders that reference Vault paths.

## Vault Secret Organization

Secrets are organized by service boundaries:

```
secret/homelab/
├── proxmox/terraform/          # Proxmox API credentials
├── freenas/
│   ├── credentials/            # TrueNAS API and passwords
│   └── ssh/                    # SSH keys
├── elasticsearch/
│   ├── passwords/              # User passwords
│   └── api-keys/               # API keys
├── kubernetes/
│   ├── cluster/                # K3s tokens and certs
│   └── kubeconfig/             # Kubeconfig files
├── apps/
│   ├── plex/                   # Media application secrets
│   ├── radarr/
│   ├── sonarr/
│   └── qbittorrent/
├── home-assistant/config/      # Home Assistant credentials
├── pihole/credentials/         # Pi-hole admin password
├── databases/
│   ├── mysql/                  # Database passwords
│   └── postgresql/
└── network/config/             # Network configuration values
```

See [VAULT-SETUP.md](VAULT-SETUP.md#secret-organization) for complete structure.

## Adding Secrets

### Using Vault CLI

Set up environment:

```bash
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY=true  # For self-signed certs
vault login  # Enter token
```

Add secrets:

```bash
# Single secret
vault kv put secret/homelab/proxmox/terraform \
  username="terraform@pve" \
  password="secure-password-here"

# Multiple fields
vault kv put secret/homelab/freenas/credentials \
  api_key="your-api-key" \
  root_password="your-password"

# From file
vault kv put secret/homelab/freenas/ssh \
  private_key=@~/.ssh/truenas_ed25519 \
  public_key=@~/.ssh/truenas_ed25519.pub
```

### Using Vault UI

1. Navigate to https://192.168.10.101:8200
2. Login with token
3. Click "secret/" → "homelab/"
4. Click "Create secret"
5. Enter path (e.g., "apps/plex")
6. Add key-value pairs
7. Click "Save"

### Bulk Import

For migrating existing secrets:

```bash
#!/bin/bash
# migrate-secrets.sh

export VAULT_ADDR="https://192.168.10.101:8200"
vault login

# Read from existing file
PROXMOX_USER=$(grep pm_user terraform.tfvars | cut -d'"' -f2)
PROXMOX_PASS=$(grep pm_password terraform.tfvars | cut -d'"' -f2)

# Store in Vault
vault kv put secret/homelab/proxmox/terraform \
  username="$PROXMOX_USER" \
  password="$PROXMOX_PASS"

echo "Migrated Proxmox credentials"
```

## Retrieving Secrets

### Via CLI

```bash
# Get all fields
vault kv get secret/homelab/proxmox/terraform

# Get specific field
vault kv get -field=password secret/homelab/proxmox/terraform

# JSON output
vault kv get -format=json secret/homelab/proxmox/terraform | \
  jq -r '.data.data.password'

# List secrets
vault kv list secret/homelab/
vault kv list secret/homelab/apps/
```

### Via API

```bash
# Get secret via HTTP API
curl -X GET \
  -H "X-Vault-Token: ${VAULT_TOKEN}" \
  https://192.168.10.101:8200/v1/secret/data/homelab/proxmox/terraform

# Parse with jq
curl -s -H "X-Vault-Token: ${VAULT_TOKEN}" \
  https://192.168.10.101:8200/v1/secret/data/homelab/proxmox/terraform | \
  jq -r '.data.data.password'
```

## Terraform Integration

### Provider Configuration

Add to your Terraform configuration:

```hcl
terraform {
  required_providers {
    vault = {
      source  = "hashicorp/vault"
      version = "~> 4.0"
    }
  }
}

provider "vault" {
  address = "https://192.168.10.101:8200"

  # Option 1: Use token from environment
  # export VAULT_TOKEN=your-token

  # Option 2: Use userpass authentication
  # auth_login_userpass {
  #   username = "terraform"
  #   password = var.vault_password
  # }

  skip_tls_verify = true  # Only for dev/self-signed certs
}
```

### Reading Secrets

```hcl
# Read Proxmox credentials
data "vault_kv_secret_v2" "proxmox" {
  mount = "secret"
  name  = "homelab/proxmox/terraform"
}

# Read TrueNAS credentials
data "vault_kv_secret_v2" "freenas" {
  mount = "secret"
  name  = "homelab/freenas/credentials"
}

# Use in provider
provider "proxmox" {
  pm_api_url  = "https://pve1.lab.thewortmans.org:8006/api2/json"
  pm_user     = data.vault_kv_secret_v2.proxmox.data["username"]
  pm_password = data.vault_kv_secret_v2.proxmox.data["password"]
  pm_tls_insecure = true
}

# Use in resources
resource "proxmox_vm_qemu" "vm" {
  name        = "example"
  cipassword  = data.vault_kv_secret_v2.proxmox.data["ci_password"]
  # ... other config
}
```

### Example: Complete Terraform File

See `/Users/bret/git/homelab/tf/vault-provider-example.tf` for a working example.

### Authentication Methods

**Token authentication (simple)**:
```bash
export VAULT_TOKEN=$(vault login -token-only)
terraform plan
```

**Userpass authentication (recommended)**:
```hcl
provider "vault" {
  auth_login_userpass {
    username = "terraform"
    password = var.vault_password  # From environment or variable
  }
}
```

## Ansible Integration

### Using hashi_vault Lookup Plugin

Install community.hashi_vault collection:

```bash
ansible-galaxy collection install community.hashi_vault
```

Use in playbooks:

```yaml
---
- name: Configure with Vault secrets
  hosts: all
  vars:
    vault_addr: "https://192.168.10.101:8200"
    vault_validate_certs: false
  tasks:
    - name: Get Proxmox password
      set_fact:
        proxmox_password: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/proxmox/terraform:password validate_certs=false') }}"

    - name: Get TrueNAS API key
      set_fact:
        truenas_api_key: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/freenas/credentials:api_key validate_certs=false') }}"

    - name: Use secret in task
      uri:
        url: "https://192.168.2.24/api/v2.0/system/info"
        headers:
          Authorization: "Bearer {{ truenas_api_key }}"
        validate_certs: no
```

### Environment Variables

Set before running Ansible:

```bash
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_TOKEN=$(vault login -token-only)
export VAULT_SKIP_VERIFY=true

ansible-playbook -i inventory playbook.yml
```

### Using with Ansible Vault (Hybrid Approach)

Store Vault token in Ansible Vault:

```bash
# Encrypt vault token
ansible-vault encrypt_string 'hvs.your-vault-token' --name 'vault_token'
```

Use in playbook:

```yaml
vars:
  vault_token: !vault |
    $ANSIBLE_VAULT;1.1;AES256
    ...encrypted...

tasks:
  - name: Get secret with encrypted token
    set_fact:
      secret: "{{ lookup('hashi_vault', 'secret=secret/data/path token=' + vault_token) }}"
```

## Kubernetes Integration

### External Secrets Operator (Recommended)

Install External Secrets Operator:

```bash
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets -n external-secrets --create-namespace
```

Create SecretStore:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: vault-backend
  namespace: default
spec:
  provider:
    vault:
      server: "https://192.168.10.101:8200"
      path: "secret"
      version: "v2"
      auth:
        tokenSecretRef:
          name: "vault-token"
          key: "token"
```

Create ExternalSecret:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: plex-secret
  namespace: media
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: plex-credentials
    creationPolicy: Owner
  data:
    - secretKey: claim-token
      remoteRef:
        key: homelab/apps/plex
        property: claim_token
```

Use in Pod:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: plex
spec:
  containers:
    - name: plex
      image: plexinc/pms-docker
      env:
        - name: PLEX_CLAIM
          valueFrom:
            secretKeyRef:
              name: plex-credentials
              key: claim-token
```

### Vault Agent Injector

Alternative: Use Vault Agent sidecar injection:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: example
  annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "myapp"
    vault.hashicorp.com/agent-inject-secret-database: "secret/data/homelab/databases/mysql"
spec:
  serviceAccountName: myapp
  containers:
    - name: app
      image: myapp:latest
```

## Secret Rotation

### Manual Rotation

Update existing secret:

```bash
# Update with new value
vault kv put secret/homelab/proxmox/terraform \
  username="terraform@pve" \
  password="new-secure-password"

# Verify version
vault kv get secret/homelab/proxmox/terraform

# View history
vault kv metadata get secret/homelab/proxmox/terraform
```

### Automated Rotation Script

```bash
#!/bin/bash
# rotate-secret.sh

SECRET_PATH="$1"
NEW_VALUE="$2"

if [ -z "$SECRET_PATH" ] || [ -z "$NEW_VALUE" ]; then
  echo "Usage: $0 <path> <new-value>"
  exit 1
fi

# Backup current version
CURRENT=$(vault kv get -format=json "$SECRET_PATH")
echo "$CURRENT" > "backup-$(date +%Y%m%d-%H%M%S).json"

# Update secret
vault kv put "$SECRET_PATH" value="$NEW_VALUE"

echo "Secret rotated. Backup saved."
```

### Rotation Schedule

Recommended rotation frequency:
- **Critical secrets** (root passwords, API keys): Every 90 days
- **Service accounts**: Every 180 days
- **Application tokens**: Every 365 days
- **SSH keys**: Every 365 days or on compromise

Use the rotation script: `/Users/bret/git/homelab/vault/scripts/04-rotate-credentials.sh`

## Best Practices

### 1. Never Hardcode Secrets

**Bad**:
```hcl
provider "proxmox" {
  pm_password = "hardcoded-password"  # NEVER DO THIS
}
```

**Good**:
```hcl
provider "proxmox" {
  pm_password = data.vault_kv_secret_v2.proxmox.data["password"]
}
```

### 2. Use Example Files

Create `.example` files with placeholders:

```yaml
# config.yaml.example
database:
  host: postgres.lab.local
  username: admin
  password: VAULT_SECRET_REFERENCE  # vault kv get secret/homelab/databases/postgresql
```

### 3. Document Secret Paths

Always include comments showing Vault path:

```yaml
api_key: your-key-here  # Vault: secret/homelab/apps/radarr:api_key
```

### 4. Minimal Permissions

Use Vault policies for least-privilege access:

```hcl
# Terraform should only read infrastructure secrets
path "secret/data/homelab/proxmox/*" {
  capabilities = ["read"]
}

# Not all of homelab
path "secret/data/homelab/*" {
  capabilities = ["read"]  # Too broad!
}
```

### 5. Secret Naming

Use consistent naming:
- **Lowercase**: `api_key` not `API_KEY`
- **Underscores**: `root_password` not `root-password`
- **Descriptive**: `elastic_password` not `password`

### 6. Version Control

Vault KV v2 keeps version history:

```bash
# View specific version
vault kv get -version=2 secret/homelab/proxmox/terraform

# Rollback to previous version
vault kv rollback -version=2 secret/homelab/proxmox/terraform

# Delete specific version
vault kv delete -versions=3 secret/homelab/proxmox/terraform
```

### 7. Audit Logging

Enable audit logging in production:

```bash
vault audit enable file file_path=/var/log/vault/audit.log
```

### 8. Token Lifecycle

Use short-lived tokens:

```bash
# Create token with TTL
vault token create -policy=terraform -ttl=1h

# Renew token
vault token renew

# Revoke when done
vault token revoke <token>
```

## Troubleshooting

### Permission Denied

```bash
# Check token policies
vault token lookup

# Test specific path
vault kv get secret/homelab/proxmox/terraform

# Check policy
vault policy read terraform
```

### Connection Refused

```bash
# Check Vault status
vault status

# Unseal if needed
vault operator unseal

# Verify network
ping 192.168.10.101
curl -k https://192.168.10.101:8200/v1/sys/health
```

### Terraform Can't Read Secrets

```bash
# Check provider config
terraform console
> data.vault_kv_secret_v2.proxmox

# Verify authentication
export VAULT_TOKEN=$(vault login -token-only)
terraform plan
```

### Ansible Lookup Fails

```bash
# Test lookup manually
ansible localhost -m debug -a "msg={{ lookup('hashi_vault', 'secret=secret/data/homelab/proxmox/terraform:password') }}"

# Check collection installed
ansible-galaxy collection list | grep hashi_vault
```

## Security Considerations

1. **Never log secrets**: Ensure secrets aren't in Terraform outputs or Ansible logs
2. **Use TLS in production**: Replace self-signed certs with proper CA-signed certificates
3. **Rotate regularly**: Follow rotation schedule
4. **Monitor access**: Review Vault audit logs
5. **Limit token TTL**: Use shortest possible token lifetime
6. **Revoke compromised tokens**: Immediately revoke if exposure suspected

## Next Steps

- Set up secret rotation schedule
- Configure audit logging
- Implement automated secret scanning
- Set up monitoring and alerting for secret access
- Train team on secret management practices

## References

- [HashiCorp Vault Documentation](https://www.vaultproject.io/docs)
- [Terraform Vault Provider](https://registry.terraform.io/providers/hashicorp/vault/latest/docs)
- [Ansible Vault Lookup](https://docs.ansible.com/ansible/latest/collections/community/hashi_vault/hashi_vault_lookup.html)
- [External Secrets Operator](https://external-secrets.io/)
