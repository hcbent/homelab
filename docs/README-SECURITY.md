# Security Setup Quick Start

This repository uses HashiCorp Vault for centralized secret management. **No secrets are committed to Git.**

## 🚀 Quick Start

### One-Command Deployment

```bash
# Run the automated deployment script
chmod +x deploy-vault-complete.sh
./deploy-vault-complete.sh
```

This will:
- Deploy Vault VM with Terraform
- Install Vault with Ansible
- Initialize and configure Vault
- Guide you through credential rotation
- Update repository security

**Time**: ~30-45 minutes

### Manual Deployment

Follow the detailed guide:

```bash
# Read the comprehensive deployment guide
cat DEPLOYMENT-GUIDE.md

# Or view in browser
open DEPLOYMENT-GUIDE.md
```

## 📚 Documentation

| Document | Purpose | When to Use |
|----------|---------|-------------|
| **SECURITY-AUDIT-SUMMARY.md** | Executive summary of security issues | Read first |
| **DEPLOYMENT-GUIDE.md** | Step-by-step deployment instructions | During setup |
| **SECURITY.md** | Security policies and best practices | Reference |
| **tf/README-VAULT.md** | Terraform + Vault integration | Terraform users |
| **ansible/README-VAULT.md** | Ansible + Vault integration | Ansible users |

## 🔐 Secret Management

### Vault Server

**URL**: https://vault.lab.thewortmans.org:8200
**IP**: 192.168.10.41

### Secret Paths

```
secret/
└── homelab/
    ├── proxmox/          # Proxmox credentials
    ├── freenas/          # TrueNAS/FreeNAS credentials
    ├── elasticsearch/    # Elasticsearch passwords
    ├── apps/            # Application API keys
    ├── home-assistant/  # Home Assistant config
    └── databases/       # Database credentials
```

### Quick Commands

```bash
# Set Vault address
export VAULT_ADDR=https://vault.lab.thewortmans.org:8200
export VAULT_SKIP_VERIFY=true

# Login
vault login

# Read a secret
vault kv get secret/homelab/proxmox/terraform

# Write a secret
vault kv put secret/homelab/apps/myapp api_key="abc123"

# List secrets
vault kv list secret/homelab/
```

## 🛠️ Usage Examples

### Terraform

```hcl
# Read Proxmox credentials from Vault
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

See: `tf/README-VAULT.md`

### Ansible

```yaml
- name: Get secret from Vault
  set_fact:
    api_key: "{{ lookup('community.hashi_vault.hashi_vault',
                 'secret=secret/data/homelab/apps/myapp:api_key') }}"
  no_log: true
```

See: `ansible/README-VAULT.md`

## 🚨 Before Sharing This Repo

Complete these steps:

- [ ] Deploy Vault VM
- [ ] Rotate exposed credentials
- [ ] Store all secrets in Vault
- [ ] Remove files with secrets
- [ ] Clean Git history
- [ ] Verify with `gitleaks detect`

See: `DEPLOYMENT-GUIDE.md`

## 📁 Repository Structure

```
homelab/
├── README-SECURITY.md              # This file
├── DEPLOYMENT-GUIDE.md             # Detailed setup guide
├── SECURITY.md                     # Security policies
├── SECURITY-AUDIT-SUMMARY.md       # Audit findings
├── deploy-vault-complete.sh        # Automated deployment
│
├── tf/
│   ├── vault/                      # Vault VM Terraform
│   ├── vault-provider-example.tf   # Usage examples
│   └── README-VAULT.md             # Terraform integration
│
├── ansible/
│   ├── playbooks/deploy_vault.yml  # Vault installation
│   ├── vault-integration-example.yml
│   └── README-VAULT.md             # Ansible integration
│
└── vault/
    ├── README.md.example           # Safe template
    └── scripts/
        ├── 01-initialize-vault.sh
        ├── 02-unseal-vault.sh
        ├── 03-configure-vault.sh
        └── 04-rotate-credentials.sh
```

## 🔧 Common Tasks

### Unseal Vault After Reboot

```bash
cd vault/scripts
./02-unseal-vault.sh
```

### Backup Vault

```bash
ssh bret@vault.lab.thewortmans.org
sudo tar -czf /tmp/vault-backup.tar.gz /var/lib/vault/
```

### Rotate a Secret

```bash
vault kv put secret/homelab/apps/myapp api_key="new-value"
```

### Update Terraform to Use Vault

1. Add Vault provider to `provider.tf`
2. Create `vault-secrets.tf` with data sources
3. Update resources to use Vault data
4. Test with `terraform plan`

See: `tf/README-VAULT.md`

### Update Ansible to Use Vault

1. Install collection: `ansible-galaxy collection install community.hashi_vault`
2. Add environment variables
3. Use `lookup('community.hashi_vault.hashi_vault', ...)`
4. Test playbook

See: `ansible/README-VAULT.md`

## ❓ Troubleshooting

### Vault is Sealed

```bash
vault operator unseal <KEY1>
vault operator unseal <KEY2>
vault operator unseal <KEY3>
```

### Permission Denied

```bash
vault login
vault token capabilities secret/data/homelab/apps/myapp
```

### TLS Issues

```bash
export VAULT_SKIP_VERIFY=true
```

## 📞 Support

- **Security Issues**: See `SECURITY.md`
- **Deployment Help**: See `DEPLOYMENT-GUIDE.md`
- **Terraform Help**: See `tf/README-VAULT.md`
- **Ansible Help**: See `ansible/README-VAULT.md`

## ✅ Verification Checklist

After deployment, verify:

```bash
# Vault is running
vault status

# Secrets exist
vault kv list secret/homelab/

# No secrets in Git
gitleaks detect --source .

# Files are gitignored
git status | grep -E "(freenas|vault/README.md)"  # Should be empty
```

## 🎯 Success Criteria

You'll know setup is complete when:

✅ Vault is deployed and unsealed
✅ All secrets are stored in Vault
✅ Exposed credentials have been rotated
✅ Terraform reads secrets from Vault
✅ Ansible reads secrets from Vault
✅ Git history is clean
✅ `gitleaks detect` finds no secrets
✅ Repository is safe to share publicly

---

**Ready to deploy?** Run `./deploy-vault-complete.sh`

**Need help?** Read `DEPLOYMENT-GUIDE.md`

**Security questions?** Read `SECURITY.md`
