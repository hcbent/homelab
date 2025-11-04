# Homelab Vault Deployment Guide

This guide walks you through deploying a secure, standalone HashiCorp Vault server and migrating all secrets from your Git repository into Vault.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Deploy Vault VM](#deploy-vault-vm)
3. [Install and Configure Vault](#install-and-configure-vault)
4. [Rotate Exposed Credentials](#rotate-exposed-credentials)
5. [Integrate with Terraform](#integrate-with-terraform)
6. [Integrate with Ansible](#integrate-with-ansible)
7. [Clean Git History](#clean-git-history)
8. [Verification](#verification)

---

## Prerequisites

### Required Tools

```bash
# Install Terraform
brew install terraform  # macOS
# OR
apt install terraform   # Ubuntu

# Install Ansible
brew install ansible    # macOS
# OR
apt install ansible     # Ubuntu

# Install Vault CLI
brew install vault      # macOS
# OR
wget https://releases.hashicorp.com/vault/1.18.3/vault_1.18.3_linux_amd64.zip
unzip vault_1.18.3_linux_amd64.zip
sudo mv vault /usr/local/bin/

# Install Python libraries for Ansible-Vault integration
pip install hvac

# Install git-filter-repo for history cleaning
brew install git-filter-repo  # macOS
# OR
pip install git-filter-repo

# Install gitleaks for secret scanning
brew install gitleaks   # macOS
```

### Network Requirements

- **Vault VM IP**: 192.168.10.41 (configured in deployment)
- **DNS Entry**: vault.lab.thewortmans.org → 192.168.10.41
- **Proxmox Access**: Must have Proxmox credentials for VM creation

---

## Step 1: Deploy Vault VM

### 1.1 Create Terraform Configuration

```bash
cd tf/vault
```

### 1.2 Create terraform.tfvars

Copy the example file and customize:

```bash
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

```hcl
pm_user     = "terraform@pve"
pm_password = "your-current-proxmox-password"  # Will rotate after Vault is setup
target_node = "pve1"
vmid        = 401
cores       = 2
memory      = 4096
disk_size   = "50G"
ipconfig0   = "ip=192.168.10.41/24,gw=192.168.10.1"
ciuser      = "bret"
cipassword  = "your-temporary-password"
sshkeys     = <<-EOT
ssh-rsa AAAAB3NzaC1yc2E... your-public-key-here
EOT
```

### 1.3 Deploy the VM

```bash
terraform init
terraform plan
terraform apply
```

**Wait for VM to be created (~2-3 minutes)**

### 1.4 Verify VM Access

```bash
# Test SSH access
ssh bret@192.168.10.41

# OR with IP
ssh bret@vault.lab.thewortmans.org
```

---

## Step 2: Install and Configure Vault

### 2.1 Deploy Vault with Ansible

```bash
cd ../../ansible

# Test connectivity
ansible -i inventory/vault vault -m ping

# Deploy Vault
ansible-playbook -i inventory/vault playbooks/deploy_vault.yml
```

This will:
- Install HashiCorp Vault 1.18.3
- Configure systemd service
- Generate self-signed TLS certificate
- Start Vault service

**Expected output**: Vault running on https://vault.lab.thewortmans.org:8200

### 2.2 Initialize Vault

```bash
cd ../vault/scripts

# Make scripts executable
chmod +x *.sh

# Initialize Vault (generates unseal keys and root token)
./01-initialize-vault.sh
```

**CRITICAL**: This will display your unseal keys and root token.

Save these in a password manager immediately! They look like:

```
Unseal Key 1: zXyAbc123...
Unseal Key 2: pQrDef456...
Unseal Key 3: jKlMno789...
Unseal Key 4: tUvGhi012...
Unseal Key 5: wXyZab345...

Initial Root Token: hvs.AbC123XyZ...
```

The script automatically:
- Creates unseal keys and root token
- Saves them to `~/.vault-secrets/vault-init-TIMESTAMP.txt`
- Unseals Vault with 3 keys
- Saves root token to `~/.vault-token`

### 2.3 Configure Vault Secret Structure

```bash
# This creates the secret paths and policies
./03-configure-vault.sh
```

This creates:
- Secret paths under `secret/homelab/`
- Policies for terraform, ansible, apps
- Userpass authentication
- Placeholder secrets (with CHANGE_ME values)

### 2.4 Verify Vault Setup

```bash
# Set environment variables
export VAULT_ADDR=https://vault.lab.thewortmans.org:8200
export VAULT_SKIP_VERIFY=true

# Check status
vault status

# Should show:
# Sealed: false
# Initialized: true

# List secret paths
vault kv list secret/homelab/

# Test reading a secret
vault kv get secret/homelab/proxmox/terraform
```

---

## Step 3: Rotate Exposed Credentials

**CRITICAL**: The following credentials were exposed in Git and MUST be rotated:

### 3.1 Run the Rotation Script

```bash
./04-rotate-credentials.sh
```

This interactive script guides you through:

### 3.2 Rotate TrueNAS Credentials

1. **Change root password**:
   - Access TrueNAS UI: https://192.168.2.24
   - Go to: Accounts → Users → root → Edit
   - Set new password
   - Save

2. **Rotate API key**:
   - Go to: API Keys
   - Delete old key: `***REMOVED***`
   - Click "+ ADD" to create new API key
   - Copy the new API key

3. **Store in Vault**:
   ```bash
   vault kv put secret/homelab/freenas/credentials \
       api_key="YOUR_NEW_API_KEY" \
       root_password="YOUR_NEW_ROOT_PASSWORD"
   ```

### 3.3 Rotate SSH Key

```bash
# Generate new SSH key
ssh-keygen -t ed25519 -f ~/.ssh/truenas_ed25519 -C "truenas-homelab"

# Copy public key
cat ~/.ssh/truenas_ed25519.pub

# Configure on TrueNAS:
# 1. SSH to TrueNAS: ssh root@192.168.2.24
# 2. Edit: vi ~/.ssh/authorized_keys
# 3. Remove old ECDSA key (starts with ecdsa-sha2-nistp256)
# 4. Add new ed25519 key
# 5. Save and exit

# Test new key
ssh -i ~/.ssh/truenas_ed25519 root@192.168.2.24

# Store in Vault
vault kv put secret/homelab/freenas/ssh \
    private_key="$(cat ~/.ssh/truenas_ed25519)" \
    public_key="$(cat ~/.ssh/truenas_ed25519.pub)"
```

### 3.4 Store All Secrets in Vault

```bash
# Proxmox credentials
vault kv put secret/homelab/proxmox/terraform \
    username="terraform@pve" \
    password="YOUR_PROXMOX_PASSWORD" \
    ssh_public_key="$(cat ~/.ssh/id_rsa.pub)"

# Elasticsearch passwords
vault kv put secret/homelab/elasticsearch/passwords \
    elastic_password="YOUR_ELASTIC_PASSWORD" \
    kibana_password="YOUR_KIBANA_PASSWORD" \
    monitoring_password="YOUR_MONITORING_PASSWORD"

# Application API keys
vault kv put secret/homelab/apps/plex claim_token="YOUR_PLEX_TOKEN"
vault kv put secret/homelab/apps/radarr api_key="YOUR_RADARR_KEY"
vault kv put secret/homelab/apps/sonarr api_key="YOUR_SONARR_KEY"
vault kv put secret/homelab/apps/lidarr api_key="YOUR_LIDARR_KEY"
```

---

## Step 4: Integrate with Terraform

### 4.1 Add Vault Provider

In each Terraform directory (`tf/lab/`, `tf/kubernetes/`, etc.), create `vault-provider.tf`:

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
  skip_tls_verify = true
}
```

### 4.2 Create Vault Data Sources

Create `vault-secrets.tf`:

```hcl
# Read Proxmox credentials from Vault
data "vault_kv_secret_v2" "proxmox" {
  mount = "secret"
  name  = "homelab/proxmox/terraform"
}

# Use in provider
locals {
  pm_user     = data.vault_kv_secret_v2.proxmox.data["username"]
  pm_password = data.vault_kv_secret_v2.proxmox.data["password"]
}
```

### 4.3 Update provider.tf

```hcl
provider "proxmox" {
  pm_api_url      = "https://pve1.lab.thewortmans.org:8006/api2/json"
  pm_user         = data.vault_kv_secret_v2.proxmox.data["username"]
  pm_password     = data.vault_kv_secret_v2.proxmox.data["password"]
  pm_tls_insecure = true
}
```

### 4.4 Authenticate and Test

```bash
# Login to Vault
vault login

# OR use userpass
vault login -method=userpass username=terraform

# Test Terraform
cd tf/lab
terraform init
terraform plan
```

See `tf/README-VAULT.md` for complete examples.

---

## Step 5: Integrate with Ansible

### 5.1 Install Ansible Collection

```bash
ansible-galaxy collection install community.hashi_vault
```

### 5.2 Use Vault in Playbooks

```yaml
---
- name: Example with Vault
  hosts: all

  environment:
    VAULT_ADDR: "https://vault.lab.thewortmans.org:8200"
    VAULT_SKIP_VERIFY: "true"

  tasks:
    - name: Get FreeNAS API key from Vault
      set_fact:
        freenas_api_key: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/freenas/credentials:api_key') }}"
      no_log: true

    - name: Use the secret
      debug:
        msg: "API key retrieved successfully"
```

### 5.3 Authenticate Before Running Playbooks

```bash
# Set environment variables
export VAULT_ADDR=https://vault.lab.thewortmans.org:8200
export VAULT_SKIP_VERIFY=true

# Login
vault login -method=userpass username=ansible

# Run playbook
ansible-playbook -i inventory playbook.yml
```

See `ansible/README-VAULT.md` for complete examples.

---

## Step 6: Clean Git History

**WARNING**: This rewrites Git history. Coordinate with all repository users!

### 6.1 Backup Your Repository

```bash
# Clone to backup location
cd ~/
git clone /Users/bret/git/homelab homelab-backup
```

### 6.2 Scan for Remaining Secrets

```bash
cd /Users/bret/git/homelab

# Scan entire repository
gitleaks detect --source . --verbose

# Should find secrets in history
```

### 6.3 Remove Secret Files from History

```bash
# Remove files with exposed secrets
git filter-repo --path k8s/helm/values/freenas-nfs.yaml --invert-paths
git filter-repo --path k8s/helm/values/freenas-iscsi.yaml --invert-paths
git filter-repo --path vault/README.md --invert-paths

# Verify secrets are removed
gitleaks detect --source . --verbose
```

### 6.4 Force Push (if using remote)

```bash
# WARNING: This will rewrite remote history!
git push --force origin main

# All collaborators must re-clone:
# git clone <repo-url> homelab-new
```

---

## Step 7: Verification

### 7.1 Verify Vault Health

```bash
# Check Vault status
vault status

# Verify all secrets exist
vault kv list secret/homelab/
vault kv get secret/homelab/proxmox/terraform
vault kv get secret/homelab/freenas/credentials
```

### 7.2 Verify Terraform Integration

```bash
cd tf/lab

# Should work without terraform.tfvars
terraform plan

# Check it can read Proxmox credentials from Vault
```

### 7.3 Verify Ansible Integration

```bash
cd ansible

# Test Vault lookup
ansible localhost -m debug -a "msg={{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/proxmox/terraform:username') }}"
```

### 7.4 Verify No Secrets in Git

```bash
# Scan for secrets
gitleaks detect --source . --verbose

# Should show: "No leaks found"

# Check files are gitignored
git status

# Should NOT show:
# - k8s/helm/values/freenas-nfs.yaml
# - k8s/helm/values/freenas-iscsi.yaml
# - vault/README.md
```

### 7.5 Verify .gitignore

```bash
# Try to add a secret file
echo "password=test" > vault/README.md

# Should be ignored
git status

# Clean up
rm vault/README.md
```

---

## Operational Tasks

### Daily Operations

#### Unseal Vault After Reboot

```bash
./vault/scripts/02-unseal-vault.sh

# OR manually:
vault operator unseal <KEY1>
vault operator unseal <KEY2>
vault operator unseal <KEY3>
```

#### Read a Secret

```bash
vault kv get secret/homelab/apps/plex
vault kv get -field=claim_token secret/homelab/apps/plex
```

#### Update a Secret

```bash
vault kv put secret/homelab/apps/plex \
    claim_token="new-token-value"
```

### Backup Vault Data

```bash
# Backup Vault data directory
ssh bret@vault.lab.thewortmans.org
sudo tar -czf /tmp/vault-backup-$(date +%Y%m%d).tar.gz /var/lib/vault/
scp bret@vault.lab.thewortmans.org:/tmp/vault-backup-*.tar.gz ~/backups/
```

### Restore Vault Data

```bash
# Stop Vault
ssh bret@vault.lab.thewortmans.org sudo systemctl stop vault

# Restore data
scp ~/backups/vault-backup-YYYYMMDD.tar.gz bret@vault.lab.thewortmans.org:/tmp/
ssh bret@vault.lab.thewortmans.org
sudo tar -xzf /tmp/vault-backup-YYYYMMDD.tar.gz -C /

# Start Vault
sudo systemctl start vault
```

---

## Troubleshooting

### Vault is Sealed

```bash
# Unseal with 3 of 5 keys
vault operator unseal <KEY1>
vault operator unseal <KEY2>
vault operator unseal <KEY3>

# Check status
vault status
```

### Permission Denied

```bash
# Check authentication
vault token lookup

# Check policy
vault token capabilities secret/data/homelab/apps/plex

# Re-authenticate
vault login
```

### TLS Certificate Issues

```bash
# Temporary: skip verification
export VAULT_SKIP_VERIFY=true

# Permanent: add CA cert to system trust store
# OR configure Vault with proper TLS certificate
```

### Terraform Can't Read Secrets

```bash
# Verify Vault authentication
echo $VAULT_TOKEN

# Login if needed
vault login

# Test data source
cd tf/lab
terraform console
> data.vault_kv_secret_v2.proxmox.data
```

---

## Next Steps

1. **Configure Auto-Unseal**: For production use, configure auto-unseal with cloud KMS
2. **Enable Audit Logging**: Monitor all Vault access
3. **Set Up Vault Backups**: Automated daily backups of Vault data
4. **Configure High Availability**: Deploy multiple Vault servers with Raft storage
5. **Implement Proper TLS**: Replace self-signed cert with proper CA-signed certificate
6. **Create Monitoring**: Set up Prometheus/Grafana monitoring for Vault
7. **Document Recovery Procedures**: Test and document disaster recovery

---

## Summary

You now have:

✅ Standalone Vault server deployed
✅ All secrets migrated to Vault
✅ Exposed credentials rotated
✅ Terraform integrated with Vault
✅ Ansible integrated with Vault
✅ Git history cleaned
✅ .gitignore updated
✅ Security documentation in place

**Your repository is now safe to share publicly!**

For questions or issues, see:
- `SECURITY.md` - Security policies
- `tf/README-VAULT.md` - Terraform-specific integration
- `ansible/README-VAULT.md` - Ansible-specific integration
