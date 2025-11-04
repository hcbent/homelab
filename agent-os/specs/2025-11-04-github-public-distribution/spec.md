# Specification: GitHub Public Distribution Readiness

## Goal
Transform this private homelab infrastructure repository into a production-quality, publicly shareable GitHub project by migrating all secrets to HashiCorp Vault, sanitizing git history of exposed credentials, and creating comprehensive documentation for external users.

## User Stories
- As a DevOps engineer, I want to safely share my homelab infrastructure code publicly without exposing any credentials or internal secrets
- As an external user discovering this repository, I want clear documentation and example configurations so I can understand and deploy this infrastructure in my own environment

## Specific Requirements

**Vault Infrastructure Completion**
- Update vault scripts (01-04) to reference correct IP address 10.101 instead of 10.41
- Complete vault initialization using 01-initialize-vault.sh with 5 key shares and threshold of 3
- Execute vault unsealing process via 02-unseal-vault.sh to make Vault operational
- Run vault configuration script 03-configure-vault.sh to set up auth methods, policies, and secret engines
- Verify Vault is accessible at vault.lab.thewortmans.org (192.168.10.101) with proper TLS
- Document the complete vault setup process including recovery procedures
- Ensure vault-token and unseal keys are stored securely per script guidance (password manager, separate locations)
- Configure auto-unseal consideration for production use (documented but not required for Phase 1)

**Secret Organization and Migration to Vault**
- Organize secrets in Vault following HashiCorp best practices by service boundaries (proxmox/, truenas/, kubernetes/, elasticsearch/, ansible/, terraform/, media-apps/, home-assistant/)
- Migrate Proxmox credentials (pm_user, pm_password) from terraform.tfvars files
- Migrate TrueNAS API keys and SSH credentials from democratic-csi configurations
- Migrate Elasticsearch passwords (ELASTIC_PASSWORD, MONITORING_PASSWORD, makerspace_es_api_key, CCHS_PASSWORD)
- Migrate media application credentials (Plex, Radarr, Sonarr, qBittorrent, Jackett) from docker configurations
- Migrate Home Assistant and Pi-hole credentials
- Migrate database passwords and API tokens
- Store network configuration values (VLAN IDs, domain names, IP ranges) in Vault for environment-specific deployments
- Update Terraform configurations to use Vault provider for secret retrieval
- Update Ansible playbooks to use Vault lookup plugins
- Verify no hardcoded credentials remain in codebase after migration

**Git History Sanitization**
- Create automated sanitization script at scripts/sanitize-git-history.sh using git-filter-repo tool
- Script must create backup branch (backup/pre-sanitization-TIMESTAMP) before any history rewriting
- Script must remove CCHS_PASSWORD, makerspace_es_api_key, ansible/inventory/vault and all files matching .gitignore secret patterns from entire git history
- Include dry-run mode in script with --dry-run flag to preview changes
- Include validation checks in script to verify sanitization completeness (scan for known secret patterns)
- Create detailed step-by-step manual documentation at docs/SANITIZING-GIT-HISTORY.md
- Manual documentation must explain what git-filter-repo does, why it's necessary, and risks involved
- Include rollback procedures in documentation for reverting sanitization if issues found
- Document how to verify clean history using git log and secret scanning tools

**Configuration File Management**
- Verify all sensitive configuration files have corresponding .example versions with sanitized placeholder values
- Ensure .gitignore includes docker-compose*.yml pattern
- Add comprehensive secret file patterns to .gitignore (*_PASSWORD, *_TOKEN, *_API_KEY, *_SECRET, .env files)
- Create example files with clear placeholder format (VAULT_SECRET_REFERENCE, your-password-here, etc.)
- Validate .example files provide sufficient structure guidance without exposing real values
- Document the .example file pattern in root README.md for external users
- Update existing .example files to reference Vault secret paths where appropriate

**Root README.md Documentation**
- Create new README.md at repository root using docs/README.md as structural reference
- Include project overview describing production-grade homelab infrastructure platform
- List key features (Terraform automation, K3s cluster, Elasticsearch, media stack, home automation)
- Provide quick start section with prerequisites (Proxmox, TrueNAS, domain/DNS, Vault)
- Link to detailed documentation under docs/ directory
- Include architecture diagram or description of three-layer approach (Infrastructure, Configuration, Application)
- Add clear section on security and secret management approach using Vault
- Provide troubleshooting guidance and links to individual component documentation

**Detailed Documentation Suite**
- Create docs/VAULT-SETUP.md covering complete Vault server provisioning, initialization, unsealing, configuration, and secret organization structure
- Create docs/SANITIZING-GIT-HISTORY.md with both automated script usage and manual step-by-step instructions
- Create docs/DEPLOYMENT-GUIDE.md with comprehensive deployment workflow (Terraform infrastructure, Ansible configuration, Kubernetes applications)
- Create docs/SECRET-MANAGEMENT.md documenting Vault usage patterns, how to add/rotate secrets, Terraform Vault provider usage, and Ansible Vault integration
- Create docs/SECURITY.md covering security best practices, network isolation, credential rotation schedule, and pre-commit hooks
- Create docs/CONTRIBUTING.md with contribution guidelines, code style, testing requirements, and PR process (if accepting external contributions)
- Add LICENSE file at repository root (determine appropriate open source license)
- Ensure all documentation cross-references related sections and maintains consistent terminology

**CI/CD Secret Scanning Automation**
- Create .github/workflows/secret-scan.yml using gitleaks action for detecting accidentally committed secrets
- Configure workflow to run on pull requests and pushes to main branch
- Set up gitleaks configuration file (.gitleaks.toml) with custom rules for homelab-specific secret patterns
- Ensure workflow fails PR if secrets detected with clear remediation guidance
- Add workflow badge to README.md showing secret scan status
- Configure workflow to use GitHub Actions secrets for any required credentials (none needed for scanning)

**CI/CD Terraform Validation Automation**
- Create .github/workflows/terraform-plan.yml running terraform fmt, validate, and plan on PRs
- Workflow should run for each terraform environment directory (lab, kubernetes, home-apps, vault)
- Use matrix strategy to parallelize terraform checks across environments
- Post terraform plan output as PR comment for review
- Configure workflow with proper Vault authentication using GitHub OIDC for accessing secrets during plan
- Set up terraform backend configuration for remote state if not already configured
- Ensure plan output is sanitized to not expose sensitive values in PR comments

**CI/CD Terraform Apply Automation**
- Create .github/workflows/terraform-apply.yml for automated terraform apply on merge to main
- Require manual approval via GitHub Environment protection rules before apply
- Apply should only run for environments with detected changes (use terraform plan -detailed-exitcode)
- Configure proper state locking to prevent concurrent applies
- Set up notifications for apply success/failure (GitHub notifications or external webhook)
- Include automated rollback trigger if apply fails critical validation checks
- Log apply output securely without exposing secrets

**Pre-commit Hooks Configuration**
- Create .pre-commit-config.yaml with hooks for secret scanning (detect-secrets), terraform formatting (terraform fmt), and ansible linting (ansible-lint)
- Include YAML syntax validation and trailing whitespace removal hooks
- Configure detect-secrets with custom patterns for homelab-specific credentials
- Create setup script (scripts/setup-pre-commit.sh) to install pre-commit framework and initialize hooks
- Document pre-commit hook usage in CONTRIBUTING.md
- Provide instructions for bypassing hooks in emergency situations (--no-verify flag guidance)
- Ensure hooks run quickly (under 30 seconds) to not disrupt development workflow

## Visual Design
No visual assets provided for this infrastructure and documentation project.

## Existing Code to Leverage

**Vault Scripts Pattern (vault/scripts/01-04)**
- Well-structured bash scripts with colored output, error handling, and user guidance
- Numbered naming convention (01, 02, 03, 04) for sequential execution
- Use this pattern for any new scripts including sanitization script
- Scripts include comprehensive comments and security warnings
- Follow the pattern of storing sensitive output in ~/.vault-secrets with restrictive permissions

**Example File Pattern (freenas-nfs.yaml.example, terraform.tfvars.example)**
- Established pattern of .example files with VAULT_SECRET_REFERENCE or your-password-here placeholders
- Include inline comments explaining what each secret is for and where to store it
- Reference related Kubernetes Secret or Vault path in comments
- Use this pattern for all configuration files requiring secrets

**.gitignore Secret Patterns**
- Comprehensive secret exclusion patterns already established (*_PASSWORD, *_TOKEN, *_API_KEY, etc.)
- Vault-specific patterns (.vault-token, .vault-secrets/, *vault-init*.json)
- Environment file patterns (.env, .env.*, *.env with !*.env.example exception)
- Extend these patterns to cover any newly discovered secret file types during implementation

**GitHub Workflows Pattern (.github/workflows/claude.yml)**
- Existing workflow structure for GitHub Actions integration
- Use similar permissions and checkout patterns for new workflows
- Follow the existing pattern of using ubuntu-latest runner
- Adopt the same YAML structure and commenting style for consistency

**Deploy Script Pattern (scripts/deploy-vault-complete.sh)**
- Comprehensive script with colored output, prerequisite checking, and tool validation
- Clear section headers with box-drawing characters for visual organization
- Implement similar UX patterns in sanitization script for consistency
- Include the same level of user prompting and confirmation for destructive operations

## Out of Scope
- Docker-compose files do not need git history sanitization, only .gitignore addition
- Deleting original docs/README.md file (user will handle separately after review)
- Actual execution of Vault server provisioning and OS installation (Vault VM assumed to exist and be accessible)
- Running the git history sanitization script in production (user will review and execute after verification)
- Making the GitHub repository public (user action after thorough verification of cleanliness)
- Implementing CONTRIBUTING.md if user decides not to accept external contributions initially
- Actual credential rotation execution via 04-rotate-credentials.sh (script exists, scheduling is user responsibility)
- Setting up Vault auto-unseal with cloud KMS (document as future enhancement but not required)
- Migrating Terraform state to remote backend (can remain local for homelab use)
- Comprehensive integration testing framework (manual testing sufficient for Phase 1)
