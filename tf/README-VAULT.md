# Using HashiCorp Vault with Terraform

This guide explains how to integrate Terraform with your standalone Vault server for secret management.

## Prerequisites

1. **Vault server running** at `https://vault.lab.thewortmans.org:8200`
2. **Vault initialized** and unsealed
3. **Secrets stored** in Vault under `secret/homelab/`

## Quick Start

### 1. Authenticate to Vault

```bash
# Set Vault address
export VAULT_ADDR=https://vault.lab.thewortmans.org:8200
export VAULT_SKIP_VERIFY=true  # For self-signed certs

# Login with token
export VAULT_TOKEN=<your-vault-token>

# OR login with userpass
vault login -method=userpass username=terraform
# Token will be saved to ~/.vault-token
```

### 2. Configure Terraform to Use Vault

Add to your `provider.tf`:

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
  address         = "https://vault.lab.thewortmans.org:8200"
  skip_tls_verify = true  # Only for dev with self-signed certs
}
```

### 3. Read Secrets from Vault

```hcl
# Read KV v2 secret
data "vault_kv_secret_v2" "proxmox_creds" {
  mount = "secret"
  name  = "homelab/proxmox/terraform"
}

# Use the secret
provider "proxmox" {
  pm_user     = data.vault_kv_secret_v2.proxmox_creds.data["username"]
  pm_password = data.vault_kv_secret_v2.proxmox_creds.data["password"]
}
```

## Authentication Methods

### Method 1: Token Authentication (Simple)

```bash
# Set token via environment variable
export VAULT_TOKEN=hvs.xxxxx

# Terraform will automatically use the token
terraform plan
```

```hcl
# Or specify in provider block (not recommended - use env var)
provider "vault" {
  address = "https://vault.lab.thewortmans.org:8200"
  token   = var.vault_token  # From tfvars file
}
```

### Method 2: Userpass Authentication (Recommended)

```hcl
provider "vault" {
  address = "https://vault.lab.thewortmans.org:8200"

  auth_login_userpass {
    username = "terraform"
    password = var.vault_password  # From environment or tfvars
  }
}
```

```bash
# Set password via environment variable
export TF_VAR_vault_password="your-vault-password"
terraform plan
```

### Method 3: Token from File

```hcl
provider "vault" {
  address = "https://vault.lab.thewortmans.org:8200"
  token   = file("~/.vault-token")  # Read from vault login
}
```

## Common Patterns

### Pattern 1: Proxmox Provider with Vault

```hcl
# Read Proxmox credentials
data "vault_kv_secret_v2" "proxmox" {
  mount = "secret"
  name  = "homelab/proxmox/terraform"
}

# Configure provider
provider "proxmox" {
  pm_api_url      = "https://pve1.lab.thewortmans.org:8006/api2/json"
  pm_user         = data.vault_kv_secret_v2.proxmox.data["username"]
  pm_password     = data.vault_kv_secret_v2.proxmox.data["password"]
  pm_tls_insecure = true
}
```

### Pattern 2: Multiple Secrets

```hcl
# Read multiple secret paths
data "vault_kv_secret_v2" "proxmox" {
  mount = "secret"
  name  = "homelab/proxmox/terraform"
}

data "vault_kv_secret_v2" "freenas" {
  mount = "secret"
  name  = "homelab/freenas/credentials"
}

data "vault_kv_secret_v2" "elasticsearch" {
  mount = "secret"
  name  = "homelab/elasticsearch/passwords"
}

# Use in resources
resource "null_resource" "example" {
  provisioner "local-exec" {
    command = "echo ${data.vault_kv_secret_v2.elasticsearch.data["elastic_password"]}"
  }
}
```

### Pattern 3: Dynamic Secrets

```hcl
# Use Vault's dynamic secrets for databases
data "vault_database_credentials" "mysql" {
  backend = "database"
  role    = "mysql-role"
}

# These credentials are dynamically generated and time-limited
resource "mysql_user" "app" {
  user     = data.vault_database_credentials.mysql.username
  password = data.vault_database_credentials.mysql.password
}
```

### Pattern 4: Passing Secrets to Modules

```hcl
module "vault_vm" {
  source = "./modules/proxmox_vm"

  name       = "vault"
  ciuser     = "bret"
  cipassword = data.vault_kv_secret_v2.proxmox.data["ci_password"]
  sshkeys    = data.vault_kv_secret_v2.proxmox.data["ssh_public_key"]
}
```

## Real-World Examples

### Example 1: Lab Environment

```hcl
# tf/lab/vault-integration.tf

data "vault_kv_secret_v2" "lab_secrets" {
  mount = "secret"
  name  = "homelab/proxmox/terraform"
}

locals {
  pm_user     = data.vault_kv_secret_v2.lab_secrets.data["username"]
  pm_password = data.vault_kv_secret_v2.lab_secrets.data["password"]
  ssh_keys    = data.vault_kv_secret_v2.lab_secrets.data["ssh_public_key"]
}

module "elasticsearch_vms" {
  source = "../modules/proxmox_vm"
  count  = length(var.elasticsearch_vms)

  # ... VM config ...
  sshkeys = local.ssh_keys
}
```

### Example 2: Kubernetes Cluster

```hcl
# tf/kubernetes/vault-integration.tf

data "vault_kv_secret_v2" "k8s_secrets" {
  mount = "secret"
  name  = "homelab/proxmox/terraform"
}

module "k8s_nodes" {
  source = "../modules/proxmox_vm"
  count  = length(var.kubernetes_vms)

  cipassword = data.vault_kv_secret_v2.k8s_secrets.data["ci_password"]
  sshkeys    = data.vault_kv_secret_v2.k8s_secrets.data["ssh_public_key"]
}
```

## Storing Secrets in Vault

Before using secrets in Terraform, store them in Vault:

```bash
# Proxmox credentials
vault kv put secret/homelab/proxmox/terraform \
  username="terraform@pve" \
  password="your-password" \
  ssh_public_key="$(cat ~/.ssh/id_rsa.pub)"

# FreeNAS credentials
vault kv put secret/homelab/freenas/credentials \
  api_key="your-api-key" \
  root_password="your-password"

# Cloud-init password
vault kv put secret/homelab/proxmox/terraform \
  ci_password="your-ci-password"
```

## Security Best Practices

### 1. Never Commit Secrets

```hcl
# GOOD: Read from Vault
data "vault_kv_secret_v2" "secret" {
  mount = "secret"
  name  = "homelab/app"
}

# BAD: Hardcoded secret
variable "password" {
  default = "hardcoded-password"  # NEVER DO THIS
}
```

### 2. Mark Outputs as Sensitive

```hcl
output "password" {
  value     = data.vault_kv_secret_v2.secret.data["password"]
  sensitive = true  # Prevents output in console
}
```

### 3. Use Separate Vault Namespaces/Paths

```
secret/
  homelab/
    proxmox/      # Infrastructure secrets
    apps/         # Application secrets
    databases/    # Database credentials
```

### 4. Rotate Vault Tokens

```bash
# Create short-lived tokens for Terraform
vault token create -policy=terraform -ttl=1h
```

### 5. Use Terraform Cloud/Enterprise for State

If using remote state, ensure it's encrypted and secured.

## Troubleshooting

### Error: "Error making API request"

```bash
# Check Vault is accessible
curl -k https://vault.lab.thewortmans.org:8200/v1/sys/health

# Check authentication
vault status
vault token lookup
```

### Error: "Permission denied"

```bash
# Check token has correct policy
vault token capabilities secret/data/homelab/proxmox/terraform

# Should show: ["read", "list"]
```

### Error: "Secret not found"

```bash
# List secrets to verify path
vault kv list secret/homelab/

# Read the secret directly
vault kv get secret/homelab/proxmox/terraform
```

### TLS Verification Issues

```hcl
provider "vault" {
  address         = "https://vault.lab.thewortmans.org:8200"
  skip_tls_verify = true  # For self-signed certificates

  # OR specify CA cert
  ca_cert_file = "/path/to/ca.crt"
}
```

## Migration from tfvars Files

To migrate from `.tfvars` files to Vault:

```bash
# 1. Read current tfvars
cat terraform.tfvars

# 2. Store each secret in Vault
vault kv put secret/homelab/proxmox/terraform \
  username="value-from-tfvars" \
  password="value-from-tfvars"

# 3. Update Terraform to use Vault data source
# (see examples above)

# 4. Remove tfvars file
rm terraform.tfvars

# 5. Test
terraform plan
```

## Quick Reference

```bash
# List all secrets under homelab
vault kv list secret/homelab/

# Read a secret
vault kv get secret/homelab/proxmox/terraform

# Read specific field
vault kv get -field=username secret/homelab/proxmox/terraform

# Update a secret
vault kv put secret/homelab/proxmox/terraform \
  username="new-value"

# Delete a secret
vault kv delete secret/homelab/proxmox/terraform
```

## Example Directory Structure

```
tf/
├── vault-provider-example.tf  # Examples of Vault usage
├── README-VAULT.md             # This file
├── lab/
│   ├── main.tf
│   ├── provider.tf             # Add Vault provider here
│   └── vault-secrets.tf        # Vault data sources
├── kubernetes/
│   ├── main.tf
│   ├── provider.tf
│   └── vault-secrets.tf
└── home-apps/
    ├── main.tf
    ├── provider.tf
    └── vault-secrets.tf
```

## Next Steps

1. Store secrets in Vault: `vault kv put secret/homelab/...`
2. Add Vault provider to your Terraform configs
3. Replace hardcoded secrets with Vault data sources
4. Test with `terraform plan`
5. Remove old `.tfvars` files
6. Update `.gitignore` to prevent future secret commits
