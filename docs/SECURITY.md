# Security Policy

## Overview

This repository contains infrastructure-as-code for a homelab environment. **No secrets should ever be committed to this repository.** All sensitive data must be stored in HashiCorp Vault or Ansible Vault.

## Secret Management

### HashiCorp Vault (Primary)

A standalone Vault server (`vault.lab.thewortmans.org`) manages all secrets for:
- Terraform (Proxmox credentials, API keys)
- Ansible (service passwords, SSH keys)
- Docker Compose applications
- Infrastructure services

**Vault Location**: `https://vault.lab.thewortmans.org:8200`

#### Secret Paths

```
secret/
└── homelab/
    ├── proxmox/          # Proxmox API credentials
    │   └── terraform
    ├── freenas/          # TrueNAS/FreeNAS credentials
    │   ├── credentials
    │   └── ssh
    ├── elasticsearch/    # Elasticsearch passwords
    │   └── passwords
    ├── apps/            # Application API keys
    │   ├── plex
    │   ├── radarr
    │   ├── sonarr
    │   └── lidarr
    ├── home-assistant/  # Home Assistant config
    └── databases/       # Database credentials
        ├── mysql
        └── postgresql
```

### Ansible Vault (Legacy/Supplementary)

For Ansible-specific secrets that don't need to be shared with other tools.

**Location**: `ansible/group_vars/all/vault.yml`, `ansible/host_vars/*/vault.yml`

## Files That Should NEVER Be Committed

### Terraform

```bash
# NEVER commit these files
*.tfvars              # Contains secrets
*.tfvars.json         # Contains secrets
terraform.tfstate     # May contain sensitive data
terraform.tfstate.*   # State backups
.terraform/           # Provider binaries and cached data
```

### Vault

```bash
# NEVER commit these files
vault/README.md                    # May contain unseal keys/tokens
vault/.vault-token                 # Authentication token
~/.vault-token                     # Local vault token
.vault-secrets/                    # Initialization data
*vault-init*.txt                   # Unseal keys and root token
*vault-init*.json                  # Unseal keys in JSON format
```

### Ansible

```bash
# NEVER commit these files
ansible/group_vars/all/vault.yml   # If not encrypted
ansible/host_vars/*/vault.yml      # If not encrypted
.vault_pass                        # Vault password file
```

### Kubernetes (Future)

```bash
# NEVER commit these files
k8s/helm/values/freenas-nfs.yaml        # Contains API keys/passwords
k8s/helm/values/freenas-iscsi.yaml      # Contains API keys/passwords
k8s/**/secrets.yaml                     # Any file containing secrets
```

### Application Secrets

```bash
# NEVER commit these files
.env                              # Environment variables
*.env                             # Environment files
docker/*/config/                  # Application configs (may contain secrets)
ELASTIC_PASSWORD                  # Password files
MONITORING_PASSWORD              # Password files
*_PASSWORD                       # Any password file
*_API_KEY                        # Any API key file
*_TOKEN                          # Any token file
```

## What CAN Be Committed

### Safe to Commit

✅ **Template files**: `*.example`, `*.template`
✅ **Documentation**: `README.md`, `CLAUDE.md`, `SECURITY.md`
✅ **Infrastructure code**: `*.tf`, `*.hcl` (without secrets)
✅ **Playbooks**: `*.yml`, `*.yaml` (without secrets)
✅ **Scripts**: `*.sh` (without embedded secrets)
✅ **Manifests**: Kubernetes YAML (without secrets)
✅ **Encrypted files**: Ansible Vault encrypted files (properly encrypted)

### Must Use References

Instead of hardcoded secrets, use references:

```hcl
# Terraform - GOOD
data "vault_kv_secret_v2" "proxmox" {
  mount = "secret"
  name  = "homelab/proxmox/terraform"
}

# Terraform - BAD
variable "pm_password" {
  default = "my-password"  # NEVER DO THIS
}
```

```yaml
# Ansible - GOOD
password: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/apps/myapp:password') }}"

# Ansible - BAD
password: "hardcoded-password"  # NEVER DO THIS
```

```yaml
# Kubernetes - GOOD
env:
  - name: API_KEY
    valueFrom:
      secretKeyRef:
        name: app-secrets
        key: api-key

# Kubernetes - BAD
env:
  - name: API_KEY
    value: "hardcoded-api-key"  # NEVER DO THIS
```

## Credential Rotation Policy

### Immediate Rotation Required

Rotate credentials immediately if:
- Committed to Git (even if later removed)
- Shared via insecure channel (email, chat, etc.)
- Exposed in logs or error messages
- Suspected compromise
- Employee/team member departure

### Regular Rotation Schedule

- **Vault root token**: Every 90 days
- **Vault unseal keys**: Annually
- **Service passwords**: Every 180 days
- **API keys**: Every 180 days
- **SSH keys**: Every 365 days
- **TLS certificates**: Before expiration (auto-renew recommended)

### Rotation Process

Use the provided script:

```bash
./vault/scripts/04-rotate-credentials.sh
```

## Reporting Security Issues

### If You Committed a Secret

1. **DO NOT** just delete the file and commit again (secret stays in history)
2. **Immediately rotate** the exposed credential
3. **Clean Git history** using `git-filter-repo`:
   ```bash
   git filter-repo --path path/to/secret/file --invert-paths
   ```
4. **Force push** to remote (coordinate with team)
5. **Verify** secret is removed from all history

### If You Find a Security Issue

1. **Do not** create a public issue
2. Contact repository maintainer privately
3. Include:
   - Description of the issue
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## Security Best Practices

### Development

1. **Use .gitignore**: Ensure all secret files are ignored
2. **Pre-commit hooks**: Scan for secrets before committing
3. **Review changes**: Always review `git diff` before committing
4. **Test in dev first**: Never test with production credentials

### Vault Usage

1. **Authenticate properly**: Use tokens with appropriate TTL
2. **Use policies**: Implement least-privilege access
3. **Enable audit logs**: Monitor all Vault access
4. **Backup unseal keys**: Store in multiple secure locations
5. **Auto-unseal**: Configure for production use

### Ansible Usage

1. **Use no_log**: Mark tasks handling secrets with `no_log: true`
2. **Encrypt Vault files**: Always encrypt `vault.yml` files
3. **Secure vault password**: Store `.vault_pass` securely (password manager)
4. **Limit permissions**: Restrict who can decrypt Vault files

### Terraform Usage

1. **Remote state**: Use encrypted remote state backend
2. **Mark sensitive**: Mark all secret outputs as `sensitive = true`
3. **Lock state**: Use state locking to prevent concurrent modifications
4. **Review plans**: Always review plan before applying

## Compliance Checklist

Before committing code:

- [ ] No passwords in plain text
- [ ] No API keys or tokens
- [ ] No private keys or certificates
- [ ] No connection strings with credentials
- [ ] All secrets use Vault references
- [ ] Sensitive outputs marked as `sensitive = true`
- [ ] Tasks handling secrets use `no_log: true`
- [ ] `.gitignore` is up to date
- [ ] Template files created for any secret-containing configs
- [ ] Documentation updated if adding new secrets

## Tools and Resources

### Secret Scanning

```bash
# Install gitleaks
brew install gitleaks

# Scan repository
gitleaks detect --source . --verbose

# Scan before commit (recommended)
gitleaks protect --verbose --redact
```

### Pre-commit Hooks

Install pre-commit hooks to prevent secret commits:

```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

### Git History Cleaning

```bash
# Install git-filter-repo
pip install git-filter-repo

# Remove sensitive file from history
git filter-repo --path path/to/secret/file --invert-paths

# Remove pattern from all files
git filter-repo --replace-text <(echo 'password=.*==>password=REDACTED')
```

## Contact

For security-related questions or to report vulnerabilities, contact:

- Repository maintainer: [Your contact info]
- Security team: [Team contact info]

## References

- [HashiCorp Vault Documentation](https://www.vaultproject.io/docs)
- [Ansible Vault Documentation](https://docs.ansible.com/ansible/latest/user_guide/vault.html)
- [Terraform Secrets Management](https://developer.hashicorp.com/terraform/tutorials/configuration-language/sensitive-variables)
- [Git Secrets Detection](https://github.com/gitleaks/gitleaks)

---

**Last Updated**: $(date +%Y-%m-%d)
**Version**: 1.0
