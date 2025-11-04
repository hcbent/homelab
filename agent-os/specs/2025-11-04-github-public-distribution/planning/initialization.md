# Feature Idea: GitHub Public Distribution Readiness

## Raw Description

Make this homelab infrastructure project suitable for distribution and public sharing on GitHub. Key requirements:
- All secrets must be stored in Vault, not in code
- GitHub project needs to be properly cleaned up before opening for public sharing
- Current state is uncertain - work was started but interrupted
- Vault server is being set up at vault.lab.thewortmans.org (192.168.10.101) but software hasn't been installed yet

## Context

This is a production-grade homelab infrastructure platform that automates deployment of Kubernetes, Elasticsearch, and various home applications using Terraform, Ansible, and ArgoCD. The project currently contains sensitive data that needs to be migrated to HashiCorp Vault before the repository can be safely shared publicly on GitHub.

## Current State Observations

### Git Status Analysis
- Modified files: `.gitignore`, `ansible/inventory/vault`, multiple vault scripts
- Deleted files: `CCHS_PASSWORD`, `makerspace_es_api_key`, `README.md`, `CLAUDE.md`, `deploy-and-setup.sh`
- New directories: `docs/`, `k8s/vault-setup/`, `.claude/` (agent-os setup)
- Vault infrastructure scripts exist in `vault/scripts/` (01-04 numbered scripts)

### Vault Integration Progress
- Vault scripts created for initialization, unsealing, configuration, and credential rotation
- Terraform vault provider example exists (`tf/vault-provider-example.tf`)
- `.gitignore` updated with comprehensive secret patterns (vault tokens, k8s secrets, env files, passwords, API keys)
- Example configuration files exist: `freenas-iscsi.yaml.example`, `freenas-nfs.yaml.example`, `terraform.tfvars.example`

### Secret Management Gaps
Based on git status and file analysis:
- Some real configuration files still exist alongside .example files (freenas-iscsi.yaml, freenas-nfs.yaml)
- Vault server VM may not be provisioned yet (vault.lab.thewortmans.org)
- Need to verify if all secrets have been migrated from code to Vault
- Deleted files in git history may still contain exposed secrets

## Success Criteria

The repository should be:
1. Safe to share publicly (no secrets in code or git history)
2. Easy for others to clone and customize for their own homelab
3. Well-documented with clear setup instructions
4. Include example configurations for all secret-requiring components
5. Have Vault as the single source of truth for all credentials
