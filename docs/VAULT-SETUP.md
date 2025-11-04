# HashiCorp Vault Setup Guide

This guide covers the complete setup of HashiCorp Vault for managing secrets in your homelab infrastructure.

## Overview

Vault provides centralized secret management with:
- **Secure Storage**: Encrypted secret storage with audit logging
- **Access Control**: Fine-grained policies for service authentication
- **Secret Rotation**: Automated credential rotation capabilities
- **Audit Trail**: Complete logging of all secret access

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Vault Server Provisioning](#vault-server-provisioning)
3. [Vault Installation](#vault-installation)
4. [Initialization](#initialization)
5. [Unsealing](#unsealing)
6. [Configuration](#configuration)
7. [Secret Organization](#secret-organization)
8. [Integration](#integration)
9. [Recovery Procedures](#recovery-procedures)
10. [Auto-Unseal (Future)](#auto-unseal-future)

## Prerequisites

### Hardware Requirements

- **VM Specifications**:
  - 2 CPU cores minimum
  - 2GB RAM minimum (4GB recommended)
  - 50GB disk space
  - Network connectivity to infrastructure hosts

### Software Requirements

- Ubuntu Server 22.04+ or equivalent Linux distribution
- Vault CLI installed locally (for administration)
- Access to Proxmox for VM creation
- DNS entry: vault.lab.thewortmans.org → 192.168.10.101

### Network Configuration

- **IP Address**: 192.168.10.101
- **Hostname**: vault.lab.thewortmans.org
- **Port**: 8200 (HTTPS)
- **Firewall**: Allow inbound TCP 8200 from infrastructure network

## Vault Server Provisioning

### Option 1: Using Terraform

```bash
cd tf/vault
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your Proxmox credentials

terraform init
terraform plan
terraform apply
```

### Option 2: Manual Provisioning

Create a VM in Proxmox with:
- Name: vault
- OS: Ubuntu Server 22.04
- CPU: 2 cores
- RAM: 4GB
- Disk: 50GB
- Network: vmbr0, IP: 192.168.10.101/24

## Vault Installation

### Using Ansible (Recommended)

```bash
cd ansible
ansible-playbook -i inventory/vault playbooks/deploy_vault.yml
```

### Manual Installation

SSH to the Vault server and install:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y wget gpg coreutils

# Add HashiCorp GPG key
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg

# Add HashiCorp repository
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list

# Install Vault
sudo apt update && sudo apt install vault

# Verify installation
vault --version
```

### Configure Vault Service

Create `/etc/vault.d/vault.hcl`:

```hcl
ui = true
disable_mlock = true

storage "file" {
  path = "/opt/vault/data"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = "false"
  tls_cert_file = "/opt/vault/tls/vault.crt"
  tls_key_file  = "/opt/vault/tls/vault.key"
}

api_addr = "https://192.168.10.101:8200"
cluster_addr = "https://192.168.10.101:8201"
```

Create data directory:

```bash
sudo mkdir -p /opt/vault/data
sudo chown -R vault:vault /opt/vault
```

Generate self-signed certificate (for development):

```bash
sudo mkdir -p /opt/vault/tls
cd /opt/vault/tls

sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout vault.key \
  -out vault.crt \
  -subj "/CN=vault.lab.thewortmans.org"

sudo chown vault:vault vault.key vault.crt
sudo chmod 600 vault.key
```

Enable and start Vault:

```bash
sudo systemctl enable vault
sudo systemctl start vault
sudo systemctl status vault
```

## Initialization

Use the automated initialization script:

```bash
cd vault/scripts
./01-initialize-vault.sh
```

The script will:
1. Check Vault status
2. Initialize with 5 key shares and threshold of 3
3. Save unseal keys and root token to `~/.vault-secrets/`
4. Automatically unseal Vault
5. Save root token to `~/.vault-token`

### Manual Initialization

```bash
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY=true

# Initialize Vault
vault operator init \
  -key-shares=5 \
  -key-threshold=3 \
  -format=json > vault-init.json

# Extract unseal keys
jq -r '.unseal_keys_b64[]' vault-init.json

# Extract root token
jq -r '.root_token' vault-init.json
```

**CRITICAL**: Store unseal keys and root token securely:
- Use a password manager (1Password, Bitwarden, LastPass)
- Store keys in separate locations
- Distribute keys to different people for production
- Never commit to version control

## Unsealing

Vault starts in a sealed state after restart. Unseal using:

```bash
cd vault/scripts
./02-unseal-vault.sh
```

The script will prompt for 3 of the 5 unseal keys.

### Manual Unsealing

```bash
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY=true

vault operator unseal  # Enter key 1
vault operator unseal  # Enter key 2
vault operator unseal  # Enter key 3

# Verify status
vault status
```

When `Sealed` shows `false`, Vault is ready.

## Configuration

Run the configuration script to set up secret paths and policies:

```bash
cd vault/scripts
./03-configure-vault.sh
```

This creates:
- KV secrets engine v2 at `secret/`
- Secret path structure (see [Secret Organization](#secret-organization))
- Access policies for Terraform, Ansible, and applications
- Userpass authentication for automation

### Manual Configuration

```bash
export VAULT_ADDR="https://192.168.10.101:8200"
vault login  # Enter root token

# Enable KV secrets engine
vault secrets enable -path=secret kv-v2

# Create policies (example)
vault policy write terraform -<<EOF
path "secret/data/homelab/proxmox/*" {
  capabilities = ["read", "list"]
}
EOF

# Enable userpass auth
vault auth enable userpass

# Create user
vault write auth/userpass/users/terraform \
  password="secure-password" \
  policies="terraform"
```

## Secret Organization

The Vault secret structure follows HashiCorp best practices, organized by service boundaries:

```
secret/
└── homelab/
    ├── proxmox/
    │   └── terraform/              # Proxmox API credentials
    │       ├── username
    │       └── password
    ├── freenas/
    │   ├── credentials/            # TrueNAS API and root password
    │   │   ├── api_key
    │   │   └── root_password
    │   └── ssh/                    # SSH keys for TrueNAS access
    │       ├── private_key
    │       └── public_key
    ├── elasticsearch/
    │   ├── passwords/              # Elasticsearch user passwords
    │   │   ├── elastic_password
    │   │   ├── kibana_password
    │   │   └── monitoring_password
    │   └── api-keys/               # Elasticsearch API keys
    │       ├── makerspace_key
    │       └── cchs_key
    ├── kubernetes/
    │   ├── cluster/                # K3s cluster secrets
    │   │   ├── token
    │   │   └── ca_cert
    │   └── kubeconfig/             # Kubeconfig files
    ├── apps/
    │   ├── plex/
    │   │   └── claim_token
    │   ├── radarr/
    │   │   └── api_key
    │   ├── sonarr/
    │   │   └── api_key
    │   ├── lidarr/
    │   │   └── api_key
    │   └── qbittorrent/
    │       └── password
    ├── home-assistant/
    │   └── config/
    │       ├── api_token
    │       ├── latitude
    │       └── longitude
    ├── pihole/
    │   └── credentials/
    │       └── admin_password
    ├── databases/
    │   ├── mysql/
    │   │   └── root_password
    │   └── postgresql/
    │       └── postgres_password
    ├── ansible/
    │   └── vault/                  # Ansible Vault passwords
    │       └── password
    ├── terraform/
    │   └── vault/                  # Terraform Vault credentials
    │       └── token
    └── network/
        └── config/                 # Network configuration values
            ├── vlan_ids
            ├── domain_names
            └── ip_ranges
```

### Adding Secrets

```bash
# Proxmox credentials
vault kv put secret/homelab/proxmox/terraform \
  username="terraform@pve" \
  password="your-secure-password"

# TrueNAS credentials
vault kv put secret/homelab/freenas/credentials \
  api_key="your-api-key" \
  root_password="your-root-password"

# Application secrets
vault kv put secret/homelab/apps/plex \
  claim_token="claim-your-token"
```

### Reading Secrets

```bash
# Get all fields
vault kv get secret/homelab/proxmox/terraform

# Get specific field
vault kv get -field=password secret/homelab/proxmox/terraform

# JSON output
vault kv get -format=json secret/homelab/proxmox/terraform | jq -r '.data.data.password'
```

## Integration

### Terraform Integration

Add Vault provider to Terraform configurations:

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
  skip_tls_verify = true

  # Use token from environment or userpass auth
  # token = var.vault_token
}

# Read secrets
data "vault_kv_secret_v2" "proxmox" {
  mount = "secret"
  name  = "homelab/proxmox/terraform"
}

# Use in provider
provider "proxmox" {
  pm_user     = data.vault_kv_secret_v2.proxmox.data["username"]
  pm_password = data.vault_kv_secret_v2.proxmox.data["password"]
}
```

See [Secret Management Guide](SECRET-MANAGEMENT.md) for detailed examples.

### Ansible Integration

Use Vault lookup plugin:

```yaml
---
- name: Configure with Vault secrets
  hosts: all
  tasks:
    - name: Get Proxmox password from Vault
      set_fact:
        proxmox_password: "{{ lookup('hashi_vault', 'secret=secret/data/homelab/proxmox/terraform:password') }}"
```

### Environment Variables

```bash
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY=true
export VAULT_TOKEN="your-token"

# Or use vault login
vault login
```

## Recovery Procedures

### Vault Restart

If Vault service restarts, it will be sealed:

```bash
# Check status
vault status

# Unseal
./vault/scripts/02-unseal-vault.sh
```

### Lost Unseal Keys

**If unseal keys are lost, data is UNRECOVERABLE**. This is by design for security.

Prevention:
- Store keys in multiple secure locations
- Use a password manager with backup
- Consider auto-unseal for production (see below)

### Forgotten Root Token

Generate new root token using unseal keys:

```bash
vault operator generate-root -init
vault operator generate-root  # Repeat with unseal keys
vault operator generate-root -decode=<encoded-token> -otp=<otp>
```

### Backup and Restore

Backup Vault data (when sealed):

```bash
sudo systemctl stop vault
sudo tar -czf vault-backup-$(date +%Y%m%d).tar.gz /opt/vault/data
sudo systemctl start vault
```

Restore (on new instance):

```bash
sudo systemctl stop vault
sudo rm -rf /opt/vault/data
sudo tar -xzf vault-backup-DATE.tar.gz -C /
sudo chown -R vault:vault /opt/vault
sudo systemctl start vault
# Unseal with original keys
```

## Auto-Unseal (Future)

For production deployments, configure auto-unseal to eliminate manual unsealing:

### Cloud KMS

```hcl
seal "awskms" {
  region     = "us-east-1"
  kms_key_id = "your-kms-key-id"
}
```

### Transit Seal (Another Vault)

```hcl
seal "transit" {
  address            = "https://vault-primary:8200"
  token              = "..."
  disable_renewal    = "false"
  key_name           = "autounseal"
  mount_path         = "transit/"
  tls_skip_verify    = "true"
}
```

## Security Best Practices

1. **TLS in Production**: Replace self-signed certificate with proper CA-signed cert
2. **Network Isolation**: Firewall Vault to only necessary networks
3. **Audit Logging**: Enable audit device for compliance
4. **Token TTLs**: Set appropriate token time-to-live values
5. **Least Privilege**: Use policies for fine-grained access control
6. **Key Rotation**: Regularly rotate credentials stored in Vault
7. **Monitoring**: Monitor Vault metrics and logs
8. **Backup**: Regular backups of Vault data directory

## Troubleshooting

### Connection Issues

```bash
# Test connectivity
curl -k https://192.168.10.101:8200/v1/sys/health

# Check DNS
nslookup vault.lab.thewortmans.org

# Verify service
ssh bret@192.168.10.101
sudo systemctl status vault
sudo journalctl -u vault -f
```

### Sealed State

```bash
vault status
# If Sealed: true
./vault/scripts/02-unseal-vault.sh
```

### Authentication Issues

```bash
# Verify token
vault token lookup

# Login with userpass
vault login -method=userpass username=terraform

# Re-generate root token if needed
vault operator generate-root -init
```

### Permission Denied

```bash
# Check policy
vault policy read terraform

# Verify token policies
vault token lookup

# Test path access
vault kv get secret/homelab/proxmox/terraform
```

## Next Steps

After Vault is set up:

1. Migrate all secrets from code to Vault (see [Secret Management](SECRET-MANAGEMENT.md))
2. Update Terraform and Ansible to use Vault (see [Deployment Guide](DEPLOYMENT-GUIDE.md))
3. Test secret retrieval and rotation
4. Set up credential rotation schedule
5. Configure monitoring and alerting

## References

- [HashiCorp Vault Documentation](https://www.vaultproject.io/docs)
- [Vault Best Practices](https://learn.hashicorp.com/tutorials/vault/production-hardening)
- [KV Secrets Engine](https://www.vaultproject.io/docs/secrets/kv/kv-v2)
- [Vault Policies](https://www.vaultproject.io/docs/concepts/policies)
