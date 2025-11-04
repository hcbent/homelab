# Spec Requirements: GitHub Public Distribution Readiness

## Initial Description

Make this homelab infrastructure project suitable for distribution and public sharing on GitHub. Key requirements:
- All secrets must be stored in Vault, not in code
- GitHub project needs to be properly cleaned up before opening for public sharing
- Current state is uncertain - work was started but interrupted
- Vault server is being set up at vault.lab.thewortmans.org (192.168.10.101) but software hasn't been installed yet

This is a production-grade homelab infrastructure platform that automates deployment of Kubernetes, Elasticsearch, and various home applications using Terraform, Ansible, and ArgoCD. The project currently contains sensitive data that needs to be migrated to HashiCorp Vault before the repository can be safely shared publicly on GitHub.

## Requirements Discussion

### First Round Questions

**Q1:** I found references to 10.41 IP addresses in the vault scripts (01-initialize-vault.sh, 02-unseal-vault.sh, etc.), but vault.lab.thewortmans.org resolves to 192.168.10.101. Should we update all script references to use 10.101 instead?

**Answer:** Update all script references from 10.41 to 10.101. Just the scripts, not documentation.

---

**Q2:** For sanitizing git history of exposed secrets (CCHS_PASSWORD, makerspace_es_api_key, etc.), would you prefer an automated script using git-filter-repo, detailed step-by-step instructions, or both?

**Answer:** BOTH - create automated script AND detailed step-by-step instructions with explanations.

---

**Q3:** I notice README.md was deleted and there's a docs/README.md. Should we create a new README.md at the root using docs/README.md as reference, or take a different approach?

**Answer:** Create a new README.md at root using docs/README.md as reference. User will delete the original later.

---

**Q4:** What about docker-compose.yml files (they appear to be new work based on git status)? Should they be included in git history sanitization or handled separately?

**Answer:** Just add it to .gitignore (not removing from git history).

---

**Q5:** For organizing secrets in Vault, do you have preferences (e.g., by service like kubernetes/, terraform/, ansible/; by environment; by secret type)?

**Answer:** No preferred structure - use best practices for Vault secret organization.

---

**Q6:** The project will need comprehensive documentation for external users. Should detailed setup guides be kept under docs/ directory with links from the main README, or would you prefer a different structure?

**Answer:** Detailed guides under docs/ directory, with links from the main README.md at root.

---

**Q7:** For CI/CD automation, which of these should be included:
- GitHub Actions for secret scanning and validation
- Automated Terraform plan/apply workflows
- Pre-commit hook automation

**Answer:** All of the above - GitHub Actions for secret scanning and validation, automated Terraform plan/apply workflows, and pre-commit hook automation.

---

**Q8:** Is there anything that should explicitly NOT be included in this work (e.g., certain files to leave as-is, specific secrets to handle separately, documentation to skip)?

**Answer:** (No specific exclusions provided beyond docker-compose handling noted in Q4)

### Existing Code to Reference

No similar existing features identified for reference.

This is a unique infrastructure security and documentation enhancement project for preparing a private repository for public distribution.

### Follow-up Questions

No follow-up questions were needed. All requirements were clearly defined in the first round of questions and answers.

## Visual Assets

### Files Provided:

No visual assets provided.

### Visual Insights:

Not applicable - this is an infrastructure security and documentation project.

## Requirements Summary

### Functional Requirements

**Secret Management:**
- Update Vault scripts to use correct IP address (10.101 instead of 10.41)
- Verify all secrets are migrated to Vault
- Ensure no secrets remain in code or configuration files
- Organize Vault secrets using HashiCorp best practices (by service/environment)

**Git History Sanitization:**
- Create automated script for removing secrets from git history using git-filter-repo
- Create detailed step-by-step documentation with explanations for manual process
- Target sensitive files: CCHS_PASSWORD, makerspace_es_api_key, ansible/inventory/vault
- Create backup branch before sanitization
- Document rollback procedures

**Configuration Management:**
- Ensure all sensitive configurations have .example versions
- Update .gitignore to exclude docker-compose*.yml files
- Verify .gitignore comprehensively covers all secret patterns
- Validate all example files have clear placeholders

**Documentation:**
- Create new root-level README.md using docs/README.md as reference
- Create detailed guides in docs/ directory:
  - VAULT-SETUP.md (Vault installation and configuration)
  - SANITIZING-GIT-HISTORY.md (Git history cleanup process)
  - DEPLOYMENT-GUIDE.md (Complete deployment instructions)
  - SECRET-MANAGEMENT.md (Vault usage patterns and best practices)
- Link detailed guides from main README
- Provide clear setup instructions for external users
- Document testing procedures for clean clone

**CI/CD Automation:**
- GitHub Actions workflow for secret scanning
- GitHub Actions workflow for Terraform plan on PRs
- GitHub Actions workflow for Terraform apply on merge
- Pre-commit hooks configuration (.pre-commit-config.yaml)
- Setup script for initializing pre-commit hooks
- Integration with Vault for secure CI/CD operations

### Reusability Opportunities

No existing similar features identified in the codebase to reuse or reference. This is a greenfield infrastructure security enhancement.

**Existing Components Available:**
- Vault scripts (01-04) - require IP address updates
- Terraform vault provider example - can be referenced for patterns
- Example configuration files (freenas-iscsi.yaml.example, freenas-nfs.yaml.example) - demonstrate the .example pattern
- Current .gitignore - already updated with secret patterns

### Scope Boundaries

**In Scope:**

**Phase 1 - Core Preparation (Primary Focus):**
- Update Vault script IP addresses from 10.41 to 10.101
- Complete verification of secret migration to Vault
- Create git history sanitization script (scripts/sanitize-git-history.sh)
- Create git history sanitization documentation (docs/SANITIZING-GIT-HISTORY.md)
- Update .gitignore with docker-compose*.yml pattern
- Verify comprehensive .gitignore coverage
- Create root-level README.md
- Create detailed documentation in docs/:
  - VAULT-SETUP.md
  - SANITIZING-GIT-HISTORY.md
  - DEPLOYMENT-GUIDE.md
  - SECRET-MANAGEMENT.md
- Verify all .example files are present and accurate
- Create testing procedures for clean clone validation

**Phase 2 - CI/CD Automation (Secondary):**
- GitHub Actions for secret scanning (.github/workflows/secret-scan.yml)
- Terraform plan workflow (.github/workflows/terraform-plan.yml)
- Terraform apply workflow (.github/workflows/terraform-apply.yml)
- Pre-commit hooks configuration (.pre-commit-config.yaml)
- Pre-commit setup script
- Integration testing automation

**Out of Scope:**
- Docker-compose file sanitization from git history (only adding to .gitignore)
- Deleting original docs/README.md (user will handle separately)
- Actual Vault server provisioning and software installation (infrastructure assumed ready)
- Executing the git history sanitization script (user will run after review)
- Making the repository public on GitHub (user action after verification)
- External contributions policy (CONTRIBUTING.md can be added later if needed)
- Vault credential rotation execution (scripts exist, user will schedule)

### Technical Considerations

**Vault Integration:**
- Vault server at vault.lab.thewortmans.org (192.168.10.101)
- Use Terraform Vault provider for accessing secrets in IaC
- Implement appropriate Vault auth methods (approle, kubernetes auth)
- Follow least-privilege access policies
- Document secret path structure clearly

**Git History Sanitization:**
- Tool: git-filter-repo (preferred over git-filter-branch)
- Must handle: files deleted from current state but in history
- Backup strategy: create backup branch before any history rewriting
- Testing: verify sanitization completeness before making public
- Provide both automated and manual approaches for flexibility

**Security Best Practices:**
- No secrets in any commit (past or present)
- Comprehensive secret scanning in CI/CD
- Pre-commit hooks prevent accidental secret commits
- Example files must not contain real credentials
- Documentation should not expose unnecessary internal network details

**Documentation Requirements:**
- Must be comprehensive enough for external users unfamiliar with this homelab
- Clear prerequisites and assumptions
- Step-by-step instructions with explanations
- Troubleshooting guidance
- Links between related documentation sections

**CI/CD Integration:**
- Workflows must not expose secrets in logs
- Use GitHub repository secrets for sensitive CI/CD values
- Terraform state backend security considerations
- Plan outputs should be reviewable in PRs
- Apply workflows gated on approvals if needed

**Testing Strategy:**
- Create temporary directory for clean clone testing
- Follow only the written documentation (no prior knowledge)
- Verify all .example files work as templates
- Confirm no git history secrets accessible
- Validate Vault integration works end-to-end

### Similar Code Patterns to Follow

**Existing Patterns in Codebase:**
- .example file pattern (freenas-iscsi.yaml.example, freenas-nfs.yaml.example)
- Vault script numbering convention (01, 02, 03, 04 prefixes)
- Documentation under docs/ directory structure
- Comprehensive .gitignore patterns for secrets

**Infrastructure-as-Code Best Practices:**
- Terraform module organization
- Ansible playbook structure
- Vault path organization by service boundary
- Secret rotation automation patterns

**Git Workflow:**
- Current branching strategy (main branch)
- Commit message conventions from recent history
- PR review expectations (will be enforced via CI/CD)
