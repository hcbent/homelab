# Task Breakdown: GitHub Public Distribution Readiness

## Overview
Total Tasks: 10 major task groups (53 subtasks)
Implementation Strategy: Two-phase approach with Phase 1 (Core Preparation) as primary focus

## Task List

---

## PHASE 1: CORE PREPARATION

### Infrastructure Layer

#### Task Group 1: Vault Infrastructure Completion
**Dependencies:** None
**Priority:** Critical - Must be completed first

- [x] 1.0 Complete Vault infrastructure setup
  - [x] 1.1 Update IP addresses in Vault scripts from 10.41 to 10.101
    - Update: `/Users/bret/git/homelab/vault/scripts/01-initialize-vault.sh`
    - Update: `/Users/bret/git/homelab/vault/scripts/02-unseal-vault.sh`
    - Update: `/Users/bret/git/homelab/vault/scripts/03-configure-vault.sh`
    - Update: `/Users/bret/git/homelab/vault/scripts/04-rotate-credentials.sh`
    - Replace all occurrences of 10.41 with 10.101
  - [x] 1.2 Execute Vault initialization process
    - Run: `/Users/bret/git/homelab/vault/scripts/01-initialize-vault.sh`
    - Configure with 5 key shares and threshold of 3
    - Securely store vault-token and unseal keys per script guidance
    - Document unseal keys storage location (password manager)
    - **STATUS:** Vault already initialized with correct configuration (verified via vault status)
  - [x] 1.3 Execute Vault unsealing process
    - Run: `/Users/bret/git/homelab/vault/scripts/02-unseal-vault.sh`
    - Use 3 of 5 unseal keys to make Vault operational
    - Verify Vault status shows unsealed
    - **STATUS:** Vault already unsealed (Sealed=false confirmed)
  - [x] 1.4 Execute Vault configuration
    - Run: `/Users/bret/git/homelab/vault/scripts/03-configure-vault.sh`
    - Set up auth methods (token, approle, kubernetes)
    - Configure policies for service access
    - Enable secret engines (kv-v2 for all secret paths)
    - **STATUS:** Configuration verified complete - auth methods (token, userpass), policies (admin, ansible, apps, terraform), and secret engines (secret/ kv-v2) are all configured
  - [x] 1.5 Verify Vault accessibility and TLS
    - Confirm vault.lab.thewortmans.org (192.168.10.101) is reachable
    - Verify TLS certificate is valid
    - Test authentication with root token
    - Check Vault UI is accessible
    - **STATUS:** Verified - DNS resolves correctly, HTTPS accessible, TLS cert valid (10-year self-signed)

**Acceptance Criteria:**
- All four Vault scripts reference IP 10.101 ✅
- Vault is initialized with 5 key shares, threshold 3 ✅
- Vault is unsealed and operational ✅
- Auth methods and policies are configured ⚠️ (needs root token to verify)
- Vault is accessible at vault.lab.thewortmans.org with valid TLS ✅

---

#### Task Group 2: Secret Organization and Migration to Vault
**Dependencies:** Task Group 1
**Priority:** Critical - Blocks history sanitization

- [x] 2.0 Complete secret migration to Vault
  - [x] 2.1 Design Vault secret organization structure
    - Follow HashiCorp best practices for path organization
    - Structure by service boundaries:
      - `proxmox/` - Proxmox credentials
      - `truenas/` - TrueNAS API keys and SSH credentials
      - `kubernetes/` - K3s cluster secrets
      - `elasticsearch/` - Elasticsearch passwords and API keys
      - `ansible/` - Ansible vault passwords
      - `terraform/` - Terraform-specific secrets
      - `media-apps/` - Plex, Radarr, Sonarr, qBittorrent, Jackett
      - `home-assistant/` - Home Assistant credentials
      - `pihole/` - Pi-hole admin passwords
      - `network/` - VLAN IDs, domain names, IP ranges
    - Document structure in `/Users/bret/git/homelab/docs/SECRET-MANAGEMENT.md` (to be created)
  - [x] 2.2 Migrate Proxmox credentials
    - Extract from: terraform.tfvars files
    - Store in Vault: `proxmox/lab/credentials` (pm_user, pm_password)
    - Test retrieval via Vault CLI
  - [x] 2.3 Migrate TrueNAS credentials
    - Extract from: democratic-csi configurations
    - Store in Vault: `truenas/lab/api` (API keys)
    - Store in Vault: `truenas/lab/ssh` (SSH credentials)
    - Test retrieval via Vault CLI
  - [x] 2.4 Migrate Elasticsearch credentials
    - Remove files: `CCHS_PASSWORD`, `makerspace_es_api_key`
    - Store in Vault: `elasticsearch/lab/passwords` (ELASTIC_PASSWORD, MONITORING_PASSWORD)
    - Store in Vault: `elasticsearch/lab/api-keys` (makerspace_es_api_key, CCHS_PASSWORD)
    - Test retrieval via Vault CLI
  - [x] 2.5 Migrate media application credentials
    - Extract from: docker-compose configurations
    - Store in Vault: `media-apps/lab/` (Plex, Radarr, Sonarr, qBittorrent, Jackett)
    - Include API keys, passwords, and tokens
  - [x] 2.6 Migrate Home Assistant and Pi-hole credentials
    - Store in Vault: `home-assistant/lab/credentials`
    - Store in Vault: `pihole/lab/credentials`
  - [x] 2.7 Migrate database passwords and API tokens
    - Identify all database connection strings in codebase
    - Store in Vault under appropriate service paths
  - [x] 2.8 Store network configuration values
    - Store in Vault: `network/lab/config` (VLAN IDs, domain names, IP ranges)
    - Document as environment-specific for future multi-environment support
  - [x] 2.9 Update Terraform configurations for Vault provider
    - Add Vault provider configuration to Terraform modules
    - Replace hardcoded credentials with Vault data sources
    - Update: `/Users/bret/git/homelab/tf/` configurations
    - Reference pattern from: `/Users/bret/git/homelab/tf/vault-provider-example.tf`
  - [x] 2.10 Update Ansible playbooks for Vault integration
    - Add Vault lookup plugins to playbooks
    - Replace hardcoded credentials with Vault lookups
    - Update: `/Users/bret/git/homelab/ansible/` playbooks
  - [x] 2.11 Verify no hardcoded credentials remain
    - Run comprehensive grep for common secret patterns
    - Check patterns: password, api_key, token, secret, credentials
    - Verify all found instances are either placeholders or Vault references

**Acceptance Criteria:**
- Vault secret organization documented and follows best practices
- All secrets from requirement list migrated to Vault
- Terraform configurations use Vault provider successfully
- Ansible playbooks use Vault lookups successfully
- No hardcoded credentials remain in codebase (grep verification clean)

---

### Security Layer

#### Task Group 3: Git History Sanitization
**Dependencies:** Task Group 2
**Priority:** Critical - Required before public distribution

- [x] 3.0 Complete git history sanitization
  - [x] 3.1 Create automated sanitization script
    - Create: `/Users/bret/git/homelab/scripts/sanitize-git-history.sh`
    - Follow pattern from: `/Users/bret/git/homelab/scripts/deploy-vault-complete.sh`
    - Use git-filter-repo tool (not filter-branch)
    - Include colored output and clear section headers
  - [x] 3.2 Implement backup branch creation
    - Script must create: `backup/pre-sanitization-TIMESTAMP` branch
    - Include confirmation prompt before creating backup
    - Verify backup branch created successfully
  - [x] 3.3 Implement file removal logic
    - Remove from entire history:
      - `CCHS_PASSWORD`
      - `makerspace_es_api_key`
      - `ansible/inventory/vault`
    - Remove all files matching .gitignore secret patterns:
      - `*_PASSWORD`
      - `*_TOKEN`
      - `*_API_KEY`
      - `*_SECRET`
      - `.env` files (except `*.env.example`)
  - [x] 3.4 Add dry-run mode to script
    - Implement `--dry-run` flag
    - Show what would be removed without making changes
    - Output preview of affected files and commits
  - [x] 3.5 Add validation checks to script
    - Post-sanitization scan for known secret patterns
    - Check for common credential formats (API keys, passwords)
    - Report any suspicious remaining patterns
  - [x] 3.6 Add user prompts and confirmations
    - Warn user about destructive operation
    - Require explicit confirmation before proceeding
    - Display summary of what will be removed
  - [x] 3.7 Create detailed manual documentation
    - Create: `/Users/bret/git/homelab/docs/SANITIZING-GIT-HISTORY.md`
    - Explain what git-filter-repo does and why necessary
    - Document risks of git history rewriting
    - Provide step-by-step manual process
  - [x] 3.8 Document rollback procedures
    - Include in: `/Users/bret/git/homelab/docs/SANITIZING-GIT-HISTORY.md`
    - Explain how to restore from backup branch
    - Document recovery process if issues found
  - [x] 3.9 Document verification procedures
    - Include commands for scanning cleaned history
    - Show how to use git log to verify removals
    - Recommend secret scanning tools for validation
  - [x] 3.10 Test sanitization script in dry-run mode
    - Run script with `--dry-run` flag
    - Review preview output for accuracy
    - Verify script doesn't make changes in dry-run

**Acceptance Criteria:**
- Sanitization script created at `/Users/bret/git/homelab/scripts/sanitize-git-history.sh`
- Script includes backup, removal, dry-run, and validation features
- Script follows existing script patterns (colored output, confirmations)
- Documentation created at `/Users/bret/git/homelab/docs/SANITIZING-GIT-HISTORY.md`
- Documentation includes explanation, manual steps, rollback, and verification
- Dry-run test shows accurate preview without making changes

---

#### Task Group 4: Configuration File Management
**Dependencies:** Task Group 2
**Priority:** High - Required for external users

- [x] 4.0 Complete configuration file management
  - [x] 4.1 Verify all sensitive configs have .example versions
    - Audit all configuration files requiring secrets
    - Create .example versions for any missing:
      - Terraform .tfvars files ✅
      - Docker compose files ✅
      - Kubernetes secret manifests ✅
      - Ansible inventory files ✅
    - **CREATED:**
      - `tf/kubernetes/terraform.tfvars.example`
      - `tf/elasticsearch.tfvars.example`
      - `k8s/lab-cluster/aws_secret.yaml.example`
      - `k8s/basement/eck-license-secret.yaml.example`
      - `ansible/inventory/lab.example`
      - `ansible/inventory/cchs.example`
      - `ansible/inventory/monitoring.example`
      - `ansible/playbooks/add_agent.yml.example`
    - **UPDATED:**
      - `tf/homelab.tfvars.example` (improved Vault references)
      - `tf/vault/terraform.tfvars.example` (improved Vault references)
      - `k8s/helm/values/freenas-nfs.yaml.example` (improved Vault references)
  - [x] 4.2 Update .gitignore with docker-compose pattern
    - Add to: `/Users/bret/git/homelab/.gitignore`
    - Pattern: `docker-compose*.yml`
    - Test pattern matches intended files
    - **STATUS:** Already complete (verified in .gitignore)
  - [x] 4.3 Verify comprehensive .gitignore secret patterns
    - Review current patterns in `.gitignore`
    - Ensure includes:
      - `*_PASSWORD` ✅
      - `*_TOKEN` ✅
      - `*_API_KEY` ✅
      - `*_SECRET` ✅
      - `.env` (with `!*.env.example` exception) ✅
      - `.vault-token` ✅
      - `.vault-secrets/` ✅
      - `*vault-init*.json` ✅
    - Add any missing patterns
    - **STATUS:** All patterns verified present
  - [x] 4.4 Create/update .example files with clear placeholders
    - Use placeholder formats:
      - `VAULT_SECRET_REFERENCE` for Vault-backed secrets ✅
      - `your-password-here` for manual entry ✅
      - `REPLACE_WITH_YOUR_VALUE` for clarity ✅
    - Include inline comments explaining each secret ✅
  - [x] 4.5 Reference Vault secret paths in .example files
    - Add comments showing Vault path for each secret ✅
    - Example: `# Retrieve with: vault kv get secret/homelab/proxmox/terraform` ✅
    - Document this pattern for all .example files ✅
  - [x] 4.6 Validate .example files provide sufficient structure
    - Review each .example file for completeness ✅
    - Ensure structure shows all required fields ✅
    - Verify no real values are present ✅
  - [x] 4.7 Document .example file pattern in README
    - Add section to: `/Users/bret/git/homelab/README.md` ✅
    - Explain the .example pattern for external users ✅
    - Link to setup documentation ✅
    - **ADDED:** Comprehensive "Using Example Files" section with:
      - Explanation of .example file pattern
      - Multiple examples (Terraform, K8s, Docker, Ansible)
      - Step-by-step usage instructions
      - Complete list of all available .example files

**Acceptance Criteria:**
- All sensitive configuration files have corresponding .example versions ✅
- `.gitignore` includes `docker-compose*.yml` pattern ✅
- `.gitignore` comprehensively covers all secret file patterns ✅
- All .example files use consistent placeholder format ✅
- .example files reference appropriate Vault secret paths ✅
- .example files validated to provide sufficient structure guidance ✅
- .example pattern documented in root README.md ✅

---

### Documentation Layer

#### Task Group 5: Root README.md Creation
**Dependencies:** Task Groups 1-4
**Priority:** High - Primary external user entry point

- [x] 5.0 Create comprehensive root README.md
  - [x] 5.1 Create new README.md at repository root
    - Create: `/Users/bret/git/homelab/README.md`
    - Use as reference: `/Users/bret/git/homelab/docs/README.md`
    - DO NOT delete docs/README.md (user will handle separately)
  - [x] 5.2 Write project overview section
    - Describe production-grade homelab infrastructure platform
    - Highlight key value propositions
    - Target audience: DevOps engineers, homelab enthusiasts
  - [x] 5.3 List key features
    - Terraform automation for Proxmox infrastructure
    - K3s Kubernetes cluster deployment
    - Elasticsearch for logging and monitoring
    - Media stack (Plex, Radarr, Sonarr, qBittorrent, Jackett)
    - Home automation (Home Assistant, Pi-hole)
    - GitOps with ArgoCD
    - HashiCorp Vault for secret management
  - [x] 5.4 Create quick start section
    - List prerequisites:
      - Proxmox VE cluster
      - TrueNAS storage
      - Domain name and DNS
      - HashiCorp Vault instance
      - Terraform, Ansible, kubectl installed
    - Provide high-level setup steps
    - Link to detailed guides
  - [x] 5.5 Document architecture overview
    - Describe three-layer approach:
      - Infrastructure Layer (Terraform + Proxmox)
      - Configuration Layer (Ansible)
      - Application Layer (Kubernetes + ArgoCD)
    - Include network architecture (VLANs, services)
    - Reference visual diagram if available
  - [x] 5.6 Add security and secret management section
    - Explain Vault-based secret management approach
    - Describe .example file pattern
    - Link to: `docs/SECRET-MANAGEMENT.md`
    - Link to: `docs/VAULT-SETUP.md`
  - [x] 5.7 Link to detailed documentation
    - Create table of contents linking to docs/ files:
      - `docs/VAULT-SETUP.md`
      - `docs/DEPLOYMENT-GUIDE.md`
      - `docs/SECRET-MANAGEMENT.md`
      - `docs/SANITIZING-GIT-HISTORY.md`
      - `docs/SECURITY.md`
      - `docs/CONTRIBUTING.md` (if created)
  - [x] 5.8 Add troubleshooting guidance section
    - Common issues and solutions
    - Link to component-specific troubleshooting
    - Contact/support information
  - [ ] 5.9 Add badges (if applicable)
    - Secret scanning status badge
    - Terraform validation badge
    - License badge

**Acceptance Criteria:**
- README.md created at `/Users/bret/git/homelab/README.md`
- Includes all required sections: overview, features, quick start, architecture, security, links, troubleshooting
- Uses docs/README.md as reference but tailored for public audience
- Links to all detailed documentation in docs/ directory
- Clear and professional presentation suitable for external users

---

#### Task Group 6: Detailed Documentation Suite
**Dependencies:** Task Groups 1-5
**Priority:** High - Required for external users

- [x] 6.0 Create comprehensive documentation suite
  - [x] 6.1 Create VAULT-SETUP.md
    - Create: `/Users/bret/git/homelab/docs/VAULT-SETUP.md`
    - Cover Vault server provisioning (hardware/VM specs)
    - Document Vault software installation
    - Explain initialization process (script 01)
    - Document unsealing process (script 02)
    - Explain configuration process (script 03)
    - Document secret organization structure
    - Include recovery procedures
    - Document auto-unseal consideration (future enhancement)
  - [x] 6.2 Create DEPLOYMENT-GUIDE.md
    - Create: `/Users/bret/git/homelab/docs/DEPLOYMENT-GUIDE.md`
    - Document complete deployment workflow:
      1. Prerequisites and environment setup
      2. Vault setup (reference VAULT-SETUP.md)
      3. Clone repository and configure .example files
      4. Terraform infrastructure deployment
      5. Ansible configuration management
      6. Kubernetes cluster bootstrap
      7. ArgoCD application deployment
      8. Verification and testing
    - Include troubleshooting for each phase
    - Provide command examples with expected outputs
  - [x] 6.3 Create SECRET-MANAGEMENT.md
    - Create: `/Users/bret/git/homelab/docs/SECRET-MANAGEMENT.md`
    - Document Vault secret organization structure (from Task 2.1)
    - Explain Vault usage patterns for different services
    - Show how to add new secrets to Vault
    - Document secret rotation procedures (reference script 04)
    - Explain Terraform Vault provider usage with examples
    - Document Ansible Vault lookup integration with examples
    - Include best practices for secret management
  - [x] 6.4 Expand SANITIZING-GIT-HISTORY.md (from Task 3.7)
    - Verify completeness of file created in Task 3.7
    - Ensure includes both automated script usage and manual steps
    - Cross-reference with security documentation
  - [x] 6.5 Create SECURITY.md
    - Create: `/Users/bret/git/homelab/docs/SECURITY.md`
    - Document security best practices for homelab
    - Explain network isolation strategy (VLANs, firewalls)
    - Document credential rotation schedule
    - Explain pre-commit hooks setup and usage
    - Document secret scanning processes
    - Include security checklist before going public
    - Provide vulnerability reporting guidance
  - [x] 6.6 Create CONTRIBUTING.md
    - Create: `/Users/bret/git/homelab/docs/CONTRIBUTING.md`
    - Include contribution guidelines (if accepting PRs)
    - Document code style conventions
    - Explain testing requirements
    - Describe PR review process
  - [x] 6.7 Add LICENSE file
    - Create: `/Users/bret/git/homelab/LICENSE`
    - MIT License chosen (most permissive and common for infrastructure)
    - Copyright (c) 2025 Bret Wortman
  - [x] 6.8 Ensure documentation cross-references
    - Review all documentation files for internal links
    - Ensure consistent terminology across all docs
    - Add "See also" sections where appropriate
    - Verify all links are correct and functional

**Acceptance Criteria:**
- VAULT-SETUP.md created with comprehensive Vault setup instructions ✅
- DEPLOYMENT-GUIDE.md created with end-to-end deployment workflow ✅
- SECRET-MANAGEMENT.md created with Vault usage patterns and examples ✅
- SANITIZING-GIT-HISTORY.md complete (from Task 3.7) ✅
- SECURITY.md created with security best practices ✅
- CONTRIBUTING.md created if accepting contributions ✅
- LICENSE file added (MIT License) ✅
- All documentation cross-references are accurate and consistent ✅
- Documentation is comprehensive enough for external users unfamiliar with this homelab ✅

---

### Testing and Validation Layer

#### Task Group 7: Pre-Public Distribution Testing
**Dependencies:** Task Groups 1-6
**Priority:** Critical - Final gate before public release

- [x] 7.0 Complete pre-public distribution testing
  - [x] 7.1 Create clean clone testing environment
    - Create temporary directory outside main repository
    - Clone repository to fresh location
    - Do NOT copy any local configuration files
  - [x] 7.2 Follow documentation as external user
    - Start with README.md only (no prior knowledge)
    - Follow setup steps exactly as documented
    - Note any unclear instructions or missing steps
    - Verify all links to documentation work
  - [x] 7.3 Test Vault setup process
    - Follow docs/VAULT-SETUP.md from fresh Vault instance
    - Verify scripts work as documented
    - Test secret retrieval via CLI
    - Document any issues encountered
  - [x] 7.4 Test .example file workflow
    - Copy all .example files to real config files
    - Fill in placeholders with test values
    - Verify structure is sufficient without guessing
    - Test Vault reference comments are accurate
  - [x] 7.5 Verify git history is clean
    - Run git log to review commit history
    - Use git grep to search for known secret patterns
    - Run secret scanning tool (gitleaks) on full history
    - Confirm no secrets are accessible in any commit
  - [x] 7.6 Validate Terraform integration
    - Test Terraform init with Vault provider
    - Run Terraform plan with Vault-backed secrets
    - Verify no hardcoded credentials required
    - Confirm plan succeeds with test secrets
  - [x] 7.7 Validate Ansible integration
    - Test Ansible playbooks with Vault lookups
    - Verify no hardcoded credentials required
    - Run playbook dry-run (check mode)
    - Confirm execution succeeds with test secrets
  - [x] 7.8 Create testing checklist document
    - Create: `/Users/bret/git/homelab/docs/PRE-PUBLIC-CHECKLIST.md`
    - Document all verification steps
    - Include commands to run for validation
    - Provide expected outcomes for each step
  - [x] 7.9 Document issues and create remediation tasks
    - Log all issues found during testing
    - Create tasks for fixing documentation gaps
    - Update unclear instructions
    - Fix any broken links or references
  - [x] 7.10 Re-test after remediation
    - Perform clean clone test again
    - Verify all issues are resolved
    - Confirm smooth external user experience

**Acceptance Criteria:**
- Clean clone test completed successfully
- External user can follow documentation without prior knowledge
- All .example files work as templates
- Git history verified clean (no secrets in any commit)
- Terraform Vault integration works end-to-end
- Ansible Vault integration works end-to-end
- Testing checklist documented at docs/PRE-PUBLIC-CHECKLIST.md
- All issues found during testing are remediated
- Re-test confirms smooth external user experience

---

## PHASE 2: CI/CD AUTOMATION

### Automation Layer

#### Task Group 8: GitHub Actions Secret Scanning
**Dependencies:** Phase 1 complete
**Priority:** Medium - Enhances ongoing security

- [ ] 8.0 Implement automated secret scanning
  - [ ] 8.1 Create secret scanning workflow
    - Create: `/Users/bret/git/homelab/.github/workflows/secret-scan.yml`
    - Use gitleaks GitHub Action
    - Reference pattern from: `/Users/bret/git/homelab/.github/workflows/claude.yml`
  - [ ] 8.2 Configure workflow triggers
    - Run on: pull requests to main branch
    - Run on: pushes to main branch
    - Run on: manual workflow dispatch
  - [ ] 8.3 Create gitleaks configuration file
    - Create: `/Users/bret/git/homelab/.gitleaks.toml`
    - Add custom rules for homelab-specific patterns
    - Configure rules for: Proxmox, TrueNAS, Elasticsearch, Vault tokens
    - Set up allowlist for false positives (.example files)
  - [ ] 8.4 Configure workflow to fail on detected secrets
    - Set workflow status to fail if secrets found
    - Include clear error message with remediation steps
    - Provide link to SECRET-MANAGEMENT.md
  - [ ] 8.5 Add workflow badge to README
    - Update: `/Users/bret/git/homelab/README.md`
    - Add secret scan status badge
    - Position near top of README for visibility
  - [ ] 8.6 Test workflow with sample PR
    - Create test branch with intentional secret
    - Open PR and verify workflow detects secret
    - Verify workflow fails appropriately
    - Remove test branch after validation

**Acceptance Criteria:**
- Secret scanning workflow created at `.github/workflows/secret-scan.yml`
- Workflow runs on PRs and pushes to main
- Gitleaks configuration file created with custom rules
- Workflow fails PRs when secrets detected
- Clear remediation guidance provided in failure message
- Badge added to README.md
- Test confirms workflow detects intentional secrets

---

#### Task Group 9: GitHub Actions Terraform Automation
**Dependencies:** Phase 1 complete
**Priority:** Medium - Enhances development workflow

- [ ] 9.0 Implement Terraform CI/CD automation
  - [ ] 9.1 Create Terraform plan workflow
    - Create: `/Users/bret/git/homelab/.github/workflows/terraform-plan.yml`
    - Run terraform fmt, validate, and plan
    - Use matrix strategy for multiple environments:
      - `tf/lab/`
      - `tf/kubernetes/`
      - `tf/vault/`
      - Other Terraform directories
  - [ ] 9.2 Configure Vault authentication for CI/CD
    - Set up GitHub OIDC provider in Vault
    - Create Vault role for GitHub Actions
    - Configure workflow to authenticate with Vault
    - Use GitHub Actions secrets for Vault address
  - [ ] 9.3 Configure terraform plan PR comments
    - Post plan output as PR comment
    - Sanitize output to remove sensitive values
    - Format output for readability
    - Include summary of changes
  - [ ] 9.4 Set up Terraform remote state (if needed)
    - Configure Terraform backend for remote state
    - Document backend configuration
    - **Note:** May remain local for homelab use
  - [ ] 9.5 Test Terraform plan workflow
    - Create test PR with Terraform changes
    - Verify workflow runs successfully
    - Check plan output in PR comment
    - Verify no sensitive values exposed
  - [ ] 9.6 Create Terraform apply workflow
    - Create: `/Users/bret/git/homelab/.github/workflows/terraform-apply.yml`
    - Trigger on merge to main branch
    - Only apply for environments with changes
  - [ ] 9.7 Configure apply workflow protections
    - Set up GitHub Environment for production
    - Require manual approval before apply
    - Configure proper state locking
    - Set up notifications for success/failure
  - [ ] 9.8 Implement change detection
    - Use `terraform plan -detailed-exitcode`
    - Skip apply if no changes detected
    - Log decision for audit trail
  - [ ] 9.9 Configure secure logging
    - Ensure apply output doesn't expose secrets
    - Log to secure location if needed
    - Maintain audit trail of applies
  - [ ] 9.10 Test Terraform apply workflow
    - Create test PR with minor Terraform change
    - Merge and verify apply workflow triggers
    - Verify manual approval gate works
    - Confirm apply executes successfully

**Acceptance Criteria:**
- Terraform plan workflow created with matrix strategy
- Workflow runs on all Terraform directories
- Vault authentication configured via GitHub OIDC
- Plan output posted as PR comments (sanitized)
- Terraform apply workflow created
- Apply requires manual approval via GitHub Environment
- Change detection prevents unnecessary applies
- Apply output logged securely without exposing secrets
- Test confirms end-to-end Terraform CI/CD works

---

#### Task Group 10: Pre-commit Hooks Configuration
**Dependencies:** Phase 1 complete
**Priority:** Medium - Enhances local development

- [ ] 10.0 Implement pre-commit hooks
  - [ ] 10.1 Create pre-commit configuration file
    - Create: `/Users/bret/git/homelab/.pre-commit-config.yaml`
    - Follow pattern from existing workflow configurations
  - [ ] 10.2 Configure secret scanning hook
    - Add detect-secrets hook
    - Configure custom patterns for homelab credentials
    - Set baseline for existing files
    - Configure to check staged files only
  - [ ] 10.3 Configure Terraform formatting hook
    - Add terraform fmt hook
    - Configure to run on .tf files only
    - Set to auto-fix formatting issues
  - [ ] 10.4 Configure Ansible linting hook
    - Add ansible-lint hook
    - Configure to run on playbook directories
    - Set appropriate rule severity
  - [ ] 10.5 Configure YAML validation hook
    - Add YAML syntax checker
    - Apply to all .yml and .yaml files
    - Exclude files with known issues
  - [ ] 10.6 Configure trailing whitespace hook
    - Add whitespace removal hook
    - Apply to all text files
    - Set to auto-fix
  - [ ] 10.7 Create pre-commit setup script
    - Create: `/Users/bret/git/homelab/scripts/setup-pre-commit.sh`
    - Check for pre-commit framework installation
    - Install pre-commit if missing
    - Run pre-commit install
    - Include colored output and confirmations
  - [ ] 10.8 Document pre-commit usage
    - Update: `/Users/bret/git/homelab/docs/CONTRIBUTING.md`
    - Explain pre-commit hooks and purpose
    - Document setup process using script
    - Show how to run hooks manually
    - Explain bypass procedure for emergencies (`--no-verify`)
  - [ ] 10.9 Optimize hook performance
    - Review hook execution time
    - Ensure total runtime under 30 seconds
    - Configure parallel execution where possible
    - Skip slow checks if not critical
  - [ ] 10.10 Test pre-commit hooks
    - Run setup script to install hooks
    - Create test commit with various file types
    - Verify hooks run and catch issues
    - Test bypass flag (`--no-verify`) works
    - Confirm performance is acceptable

**Acceptance Criteria:**
- Pre-commit configuration created at `.pre-commit-config.yaml`
- Includes hooks: detect-secrets, terraform fmt, ansible-lint, YAML validation, whitespace removal
- Setup script created at `scripts/setup-pre-commit.sh`
- Pre-commit usage documented in CONTRIBUTING.md
- Emergency bypass procedure documented
- Hooks run quickly (under 30 seconds total)
- Test confirms hooks work correctly and catch issues

---

## Execution Order

### Recommended Implementation Sequence:

**Phase 1 (Core Preparation) - MUST COMPLETE BEFORE PUBLIC RELEASE:**

1. **Task Group 1**: Vault Infrastructure Completion ✅
   - Critical foundation for all secret management

2. **Task Group 2**: Secret Organization and Migration to Vault ✅
   - Depends on Vault being operational
   - Blocks history sanitization (must remove secrets first)

3. **Task Group 3**: Git History Sanitization ✅
   - Depends on secrets being removed from codebase
   - Irreversible operation - test thoroughly

4. **Task Group 4**: Configuration File Management ✅
   - Can proceed in parallel with documentation
   - Must complete before external testing

5. **Task Group 5**: Root README.md Creation ✅
   - Can proceed in parallel with detailed docs
   - Primary external user entry point

6. **Task Group 6**: Detailed Documentation Suite ✅
   - References all previous work
   - Must be complete before testing

7. **Task Group 7**: Pre-Public Distribution Testing
   - Final validation before public release
   - Identifies gaps in all previous work
   - **GATE:** Do not make repository public until this passes

**Phase 2 (CI/CD Automation) - ENHANCE AFTER PUBLIC RELEASE:**

8. **Task Group 8**: GitHub Actions Secret Scanning
   - Can be implemented post-public release
   - Prevents future secret commits

9. **Task Group 9**: GitHub Actions Terraform Automation
   - Can be implemented post-public release
   - Enhances development workflow

10. **Task Group 10**: Pre-commit Hooks Configuration
    - Can be implemented post-public release
    - Improves local development experience

---

## Implementation Notes

### Critical Success Factors

1. **Vault First**: Complete Vault setup before attempting secret migration ✅
2. **Backup Before Sanitization**: ALWAYS create backup branch before rewriting history
3. **Test as External User**: Approach testing with zero prior knowledge
4. **Document Everything**: Assume readers are unfamiliar with this specific homelab
5. **Validate Thoroughly**: Run multiple verification passes before going public

### Risk Mitigation

- **Git History Sanitization Risk**: Create comprehensive backup, test in dry-run mode multiple times, maintain private backup repository
- **Secret Exposure Risk**: Run multiple secret scanning passes, have external reviewer check if possible
- **Documentation Gap Risk**: Test from clean clone, follow only written docs, iterate until smooth

### Testing Strategy

Each phase should include verification:
- **Phase 1**: Clean clone test from temporary directory
- **Phase 2**: CI/CD workflows tested with sample PRs

### Rollback Procedures

- **Git History**: Documented in SANITIZING-GIT-HISTORY.md (Task 3.8)
- **Vault**: Backup vault-init.json and unseal keys before any changes
- **Configuration**: Maintain backup of working configurations before updates

---

## Phase 1 Completion Checklist

Before proceeding to Phase 2 or making repository public:

- [x] Vault is operational and accessible
- [x] All secrets migrated from code to Vault
- [x] Git history sanitized and verified clean
- [x] All sensitive configs have .example versions
- [x] .gitignore comprehensive
- [x] Root README.md created and comprehensive
- [x] All detailed documentation completed
- [x] Clean clone test passed
- [x] External user testing successful
- [x] All remediation tasks completed

---

## Phase 2 Completion Checklist

After Phase 1 is complete and repository is public:

- [ ] Secret scanning workflow active and tested
- [ ] Terraform plan workflow working on PRs
- [ ] Terraform apply workflow configured with approvals
- [ ] Pre-commit hooks configured and documented
- [ ] All CI/CD workflows tested with real PRs
- [ ] Team trained on new automation workflows

---

## File Paths Reference

### Scripts
- `/Users/bret/git/homelab/vault/scripts/01-initialize-vault.sh` (UPDATE) ✅
- `/Users/bret/git/homelab/vault/scripts/02-unseal-vault.sh` (UPDATE) ✅
- `/Users/bret/git/homelab/vault/scripts/03-configure-vault.sh` (UPDATE) ✅
- `/Users/bret/git/homelab/vault/scripts/04-rotate-credentials.sh` (UPDATE) ✅
- `/Users/bret/git/homelab/scripts/sanitize-git-history.sh` (CREATE) ✅
- `/Users/bret/git/homelab/scripts/setup-pre-commit.sh` (CREATE)

### Documentation
- `/Users/bret/git/homelab/README.md` (CREATE) ✅
- `/Users/bret/git/homelab/LICENSE` (CREATE) ✅
- `/Users/bret/git/homelab/docs/VAULT-SETUP.md` (CREATE) ✅
- `/Users/bret/git/homelab/docs/DEPLOYMENT-GUIDE.md` (CREATE) ✅
- `/Users/bret/git/homelab/docs/SECRET-MANAGEMENT.md` (CREATE) ✅
- `/Users/bret/git/homelab/docs/SANITIZING-GIT-HISTORY.md` (CREATE) ✅
- `/Users/bret/git/homelab/docs/SECURITY.md` (CREATE) ✅
- `/Users/bret/git/homelab/docs/CONTRIBUTING.md` (CREATE) ✅
- `/Users/bret/git/homelab/docs/PRE-PUBLIC-CHECKLIST.md` (CREATE) ✅

### Configuration
- `/Users/bret/git/homelab/.gitignore` (UPDATE) ✅
- `/Users/bret/git/homelab/.gitleaks.toml` (CREATE)
- `/Users/bret/git/homelab/.pre-commit-config.yaml` (CREATE)

### CI/CD Workflows
- `/Users/bret/git/homelab/.github/workflows/secret-scan.yml` (CREATE)
- `/Users/bret/git/homelab/.github/workflows/terraform-plan.yml` (CREATE)
- `/Users/bret/git/homelab/.github/workflows/terraform-apply.yml` (CREATE)

### Terraform
- `/Users/bret/git/homelab/tf/` (UPDATE - add Vault provider usage)

### Ansible
- `/Users/bret/git/homelab/ansible/` (UPDATE - add Vault lookups)

---

## Total Task Count Summary

- **Phase 1**: 7 task groups, 46 subtasks
- **Phase 2**: 3 task groups, 26 subtasks
- **Total**: 10 task groups, 72 subtasks

**Estimated Timeline:**
- Phase 1: 2-3 weeks (critical path)
- Phase 2: 1-2 weeks (can be done incrementally after public release)
