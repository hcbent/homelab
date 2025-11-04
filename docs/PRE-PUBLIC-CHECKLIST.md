# Pre-Public Distribution Checklist

Complete verification checklist before making this repository public.

## Overview

This checklist ensures your repository is safe to share publicly with:
- Zero secrets in code or history
- Comprehensive documentation for external users
- Proper configuration examples
- Functional integrations

## Critical Security Checks

### 1. Vault Setup Complete

- [ ] Vault server deployed and accessible at 192.168.10.101
- [ ] Vault initialized with 5 key shares, threshold of 3
- [ ] Unseal keys stored securely in password manager
- [ ] Root token stored securely (separate from unseal keys)
- [ ] Vault unsealed and operational
- [ ] Secret structure configured (`secret/homelab/...`)
- [ ] Policies created (terraform, ansible, apps, admin)
- [ ] Test secret retrieval works:
  ```bash
  vault kv get secret/homelab/proxmox/terraform
  ```

### 2. All Secrets Migrated to Vault

- [ ] Proxmox credentials in Vault
- [ ] TrueNAS API keys and passwords in Vault
- [ ] TrueNAS SSH keys in Vault
- [ ] Elasticsearch passwords in Vault
- [ ] Media app API keys in Vault (Plex, Radarr, Sonarr, etc.)
- [ ] Home Assistant credentials in Vault
- [ ] Pi-hole passwords in Vault
- [ ] Database passwords in Vault
- [ ] Network configuration values in Vault
- [ ] No hardcoded credentials remain in code:
  ```bash
  cd /Users/bret/git/homelab
  grep -r "password=" . --include="*.tf" --include="*.yml"
  # Should only show comments or Vault references
  ```

### 3. Exposed Credentials Rotated

- [ ] TrueNAS root password changed
- [ ] TrueNAS API key regenerated
- [ ] TrueNAS SSH keys regenerated
- [ ] Vault unseal keys regenerated (if were exposed)
- [ ] Vault root token regenerated
- [ ] All rotated credentials stored in Vault
- [ ] Old credentials verified as non-functional

### 4. Git History Sanitized

- [ ] Backup branch created: `backup/pre-sanitization-TIMESTAMP`
- [ ] Sensitive files removed from history:
  - `CCHS_PASSWORD`
  - `makerspace_es_api_key`
  - `ansible/inventory/vault`
  - `ELASTIC_PASSWORD`
  - `MONITORING_PASSWORD`
  - `k8s/helm/values/freenas-nfs.yaml`
  - `k8s/helm/values/freenas-iscsi.yaml`
  - `vault/README.md`
- [ ] Verification commands run clean:
  ```bash
  git log --all -- CCHS_PASSWORD  # Should be empty
  git log --all -- makerspace_es_api_key  # Should be empty
  ```
- [ ] Secret scanning shows no issues:
  ```bash
  gitleaks detect --source . --verbose  # Should show no leaks
  ```
- [ ] Sanitization script dry-run reviewed:
  ```bash
  ./scripts/sanitize-git-history.sh --dry-run
  ```

### 5. Configuration Files Proper

- [ ] All sensitive configs have `.example` versions:
  - `terraform.tfvars.example` in all tf/ directories
  - `freenas-nfs.yaml.example`
  - `freenas-iscsi.yaml.example`
  - Any other configs with secrets
- [ ] `.example` files have placeholders (not real values):
  - Use `VAULT_SECRET_REFERENCE`
  - Use `your-password-here`
  - Use `REPLACE_WITH_YOUR_VALUE`
- [ ] `.example` files include Vault path comments:
  ```yaml
  password: VAULT_SECRET_REFERENCE  # vault kv get secret/homelab/service/credentials
  ```
- [ ] Real config files are gitignored:
  ```bash
  git status  # Should not show real config files
  ```

### 6. .gitignore Comprehensive

- [ ] Docker compose files excluded: `docker-compose*.yml`
- [ ] Pattern-based exclusions:
  - `*_PASSWORD`
  - `*_TOKEN`
  - `*_API_KEY`
  - `*_SECRET`
- [ ] Vault files excluded:
  - `.vault-token`
  - `.vault-secrets/`
  - `*vault-init*.json`
  - `*vault-init*.txt`
- [ ] Environment files: `.env` (but not `*.env.example`)
- [ ] Key files: `*.pem`, `*.key` (but not `*.pub`)
- [ ] Backup files: `*.backup`, `*.bak`, `*.old`
- [ ] Test exclusions work:
  ```bash
  touch TEST_PASSWORD
  git status  # Should not show TEST_PASSWORD
  rm TEST_PASSWORD
  ```

## Documentation Checks

### 7. Root README.md Created

- [ ] File exists at `/Users/bret/git/homelab/README.md`
- [ ] Includes project overview and key features
- [ ] Lists prerequisites clearly
- [ ] Provides quick start section
- [ ] Describes architecture (3-layer approach)
- [ ] Explains security and secret management
- [ ] Links to detailed documentation in `docs/`
- [ ] Includes troubleshooting section
- [ ] Professional and welcoming tone for external users

### 8. Detailed Documentation Complete

- [ ] `docs/VAULT-SETUP.md` exists and comprehensive
  - Vault provisioning steps
  - Installation instructions
  - Initialization process
  - Secret organization structure
  - Recovery procedures
- [ ] `docs/DEPLOYMENT-GUIDE.md` exists and comprehensive
  - End-to-end deployment workflow
  - All phases documented
  - Troubleshooting section
- [ ] `docs/SECRET-MANAGEMENT.md` exists and comprehensive
  - Vault usage patterns
  - Terraform integration examples
  - Ansible integration examples
  - Secret rotation procedures
- [ ] `docs/SANITIZING-GIT-HISTORY.md` exists and comprehensive
  - Automated script usage
  - Manual step-by-step instructions
  - Rollback procedures
  - Verification steps
- [ ] `docs/SECURITY.md` exists and comprehensive
  - Security best practices
  - Network isolation
  - Credential rotation schedule
  - Pre-commit hooks
  - Secret scanning
- [ ] `docs/PRE-PUBLIC-CHECKLIST.md` (this file) complete
- [ ] All documentation cross-references work
- [ ] No broken links between documents

## Integration Tests

### 9. Terraform Vault Integration

- [ ] Vault provider configured in Terraform
- [ ] Test can read Proxmox credentials:
  ```bash
  cd /Users/bret/git/homelab/tf/kubernetes
  terraform console
  > data.vault_kv_secret_v2.proxmox.data
  # Should show username and password from Vault
  ```
- [ ] Terraform plan succeeds without terraform.tfvars:
  ```bash
  export VAULT_TOKEN=$(vault login -token-only)
  terraform plan  # Should work with Vault secrets
  ```
- [ ] No hardcoded credentials in any .tf files:
  ```bash
  grep -r "password.*=" tf/ --include="*.tf" | grep -v "data.vault"
  # Should only show Vault references
  ```

### 10. Ansible Vault Integration

- [ ] community.hashi_vault collection installed:
  ```bash
  ansible-galaxy collection list | grep hashi_vault
  ```
- [ ] Test Vault lookup works:
  ```bash
  export VAULT_ADDR="https://192.168.10.101:8200"
  vault login
  ansible localhost -m debug \
    -a "msg={{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/proxmox/terraform:username') }}"
  # Should return username from Vault
  ```
- [ ] Playbooks use Vault lookups (not hardcoded secrets)
- [ ] No secrets in unencrypted Ansible files:
  ```bash
  grep -r "password:" ansible/ --include="*.yml" | grep -v "lookup"
  # Should only show Vault lookups
  ```

### 11. Clean Clone Test

- [ ] Create test directory:
  ```bash
  mkdir -p /tmp/homelab-test
  cd /tmp/homelab-test
  ```
- [ ] Clone repository fresh:
  ```bash
  git clone /Users/bret/git/homelab .
  ```
- [ ] No secrets present in clone:
  ```bash
  gitleaks detect --source . --verbose
  # Should show "No leaks found"
  ```
- [ ] All `.example` files present:
  ```bash
  find . -name "*.example" -type f
  # Should list all example files
  ```
- [ ] No real config files (only examples):
  ```bash
  ls -la tf/kubernetes/terraform.tfvars  # Should NOT exist
  ls -la tf/kubernetes/terraform.tfvars.example  # Should exist
  ```
- [ ] README.md readable and makes sense
- [ ] Can follow quick start (with test Vault instance)
- [ ] Cleanup test:
  ```bash
  rm -rf /tmp/homelab-test
  ```

## External User Testing

### 12. Documentation Walkthrough

- [ ] Start from `README.md` only (no prior knowledge)
- [ ] Prerequisites list is complete
- [ ] Quick start steps are clear
- [ ] Links to detailed docs work
- [ ] Can understand architecture without asking questions
- [ ] Security section explains Vault approach
- [ ] Troubleshooting section helpful

### 13. Example Files Test

- [ ] Copy each `.example` file to real name
- [ ] Placeholders are obvious and clear
- [ ] Comments explain what each value is for
- [ ] Vault path references are correct
- [ ] File structure is sufficient (not missing fields)
- [ ] No confusion about what to replace

### 14. Setup Procedure Test

Using test environment (if possible):
- [ ] Follow `docs/VAULT-SETUP.md` from scratch
- [ ] Scripts work as documented
- [ ] Secret organization makes sense
- [ ] Vault integration instructions clear
- [ ] No undocumented steps required
- [ ] Can complete setup without existing knowledge

## Automation and CI/CD

### 15. Secret Scanning Automation (Phase 2)

If implemented:
- [ ] `.github/workflows/secret-scan.yml` exists
- [ ] Gitleaks action configured
- [ ] `.gitleaks.toml` configuration present
- [ ] Workflow runs on PRs and pushes
- [ ] Test workflow with intentional secret (then remove)
- [ ] Badge added to README.md

### 16. Pre-Commit Hooks (Phase 2)

If implemented:
- [ ] `.pre-commit-config.yaml` exists
- [ ] Setup script at `scripts/setup-pre-commit.sh`
- [ ] Hooks include: gitleaks, terraform fmt, ansible-lint
- [ ] Hooks run in under 30 seconds
- [ ] Documentation in `docs/CONTRIBUTING.md`
- [ ] Test hooks catch secrets

## Final Verification

### 17. Repository Scan

- [ ] Full repository secret scan clean:
  ```bash
  cd /Users/bret/git/homelab
  gitleaks detect --source . --log-level debug
  ```
- [ ] Pattern search shows no secrets:
  ```bash
  grep -r "BEGIN.*PRIVATE KEY" . 2>/dev/null
  grep -r "password.*=" . --include="*.tf" --include="*.yml"
  ```
- [ ] File size check (no large binaries):
  ```bash
  find . -type f -size +10M
  # Should only be legitimate large files
  ```
- [ ] Git history size reasonable:
  ```bash
  du -sh .git
  # Should be reduced after sanitization
  ```

### 18. Issue Tracking

- [ ] All issues found during testing documented
- [ ] Issues categorized (critical, important, nice-to-have)
- [ ] Critical issues resolved
- [ ] Important issues resolved or documented as known issues
- [ ] Re-test after resolving issues

### 19. Backup Before Public

- [ ] Full repository backup:
  ```bash
  cd ~
  git clone --mirror /Users/bret/git/homelab homelab-backup.git
  ```
- [ ] Vault data backup:
  ```bash
  ssh vault.lab.thewortmans.org
  sudo tar -czf ~/vault-backup-$(date +%Y%m%d).tar.gz /opt/vault/data
  ```
- [ ] Backups stored in secure location
- [ ] Test backup restoration

### 20. Team Notification

If team/collaborators exist:
- [ ] All team members notified of public release
- [ ] Ensure everyone has latest secrets from Vault
- [ ] Verify no one has local uncommitted secrets
- [ ] Coordinate on timing for making public
- [ ] Confirm everyone has re-cloned after sanitization

## Making Repository Public

### 21. GitHub Settings (When Ready)

- [ ] Review repository description
- [ ] Add relevant topics/tags
- [ ] Ensure LICENSE file is appropriate
- [ ] Set up GitHub Pages (if documentation site desired)
- [ ] Configure branch protection rules
- [ ] Enable security advisories
- [ ] Enable Dependabot (if applicable)

### 22. Post-Public Monitoring

First 48 hours after making public:
- [ ] Monitor for security scan alerts
- [ ] Watch for unexpected forks
- [ ] Check for issues opened by external users
- [ ] Review any PRs from external contributors
- [ ] Verify no secrets were somehow exposed
- [ ] Monitor Vault access logs

## Verification Commands Summary

Run all these commands and verify expected results:

```bash
# 1. No secrets in current state
cd /Users/bret/git/homelab
gitleaks detect --source . --verbose

# 2. No secrets in history
gitleaks detect --source . --log-level debug

# 3. Specific file checks
git log --all -- CCHS_PASSWORD
git log --all -- makerspace_es_api_key

# 4. Pattern checks
grep -r "password=" . --include="*.tf" | grep -v vault
grep -r "api_key=" . --include="*.yml" | grep -v lookup

# 5. Vault connectivity
export VAULT_ADDR="https://192.168.10.101:8200"
vault status  # Should show unsealed
vault kv list secret/homelab/  # Should list secret paths

# 6. Terraform integration
cd tf/kubernetes
terraform console <<EOF
data.vault_kv_secret_v2.proxmox.data
EOF

# 7. Clean clone test
cd /tmp
git clone /Users/bret/git/homelab homelab-clean-test
cd homelab-clean-test
gitleaks detect --source . --verbose
cd /tmp && rm -rf homelab-clean-test

# 8. File exclusion test
cd /Users/bret/git/homelab
touch TEST_SECRET_PASSWORD
git status | grep TEST_SECRET  # Should not appear
rm TEST_SECRET_PASSWORD
```

## Sign-Off

Before making repository public, sign off on each category:

- [ ] **Security**: All secrets removed, rotated, and in Vault
- [ ] **History**: Git history completely sanitized
- [ ] **Configuration**: All .example files created and correct
- [ ] **Documentation**: Complete and accurate for external users
- [ ] **Integration**: Terraform and Ansible work with Vault
- [ ] **Testing**: Clean clone test passed
- [ ] **Verification**: All verification commands passed
- [ ] **Backup**: Full backups created and tested

**Final Approval**:
- Date: _______________
- By: _______________
- Notes: _______________

## Rollback Plan

If issues discovered after making public:

1. **Immediate**: Make repository private again
2. **Assess**: Determine scope of exposure
3. **Rotate**: Change all potentially exposed credentials
4. **Fix**: Address the issues found
5. **Re-verify**: Run full checklist again
6. **Re-publish**: Make public only after verification

## Support and Maintenance

After going public:
- Monitor repository for issues
- Respond to external questions promptly
- Keep documentation updated
- Regular security scans (weekly for first month)
- Review and merge appropriate community contributions

## References

- [Git History Sanitization Guide](SANITIZING-GIT-HISTORY.md)
- [Vault Setup Guide](VAULT-SETUP.md)
- [Secret Management Guide](SECRET-MANAGEMENT.md)
- [Security Policy](SECURITY.md)
- [Deployment Guide](DEPLOYMENT-GUIDE.md)

---

**Note**: This checklist should be completed thoroughly. Do not rush to make repository public. Taking time to verify everything protects both you and potential users of this repository.
