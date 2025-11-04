# Decisions Document: GitHub Public Distribution Readiness

## Feature Overview

**Objective**: Prepare the homelab infrastructure repository for safe public distribution on GitHub by migrating all secrets to HashiCorp Vault, sanitizing git history, and creating comprehensive documentation.

**Context**: Production-grade homelab infrastructure platform automating deployment of Kubernetes, Elasticsearch, and home applications using Terraform, Ansible, and ArgoCD. Currently contains sensitive data that must be secured before public sharing.

---

## Key Decisions from Requirements Gathering

### Round 1: Initial Requirements

#### 1. Vault Script IP Address Correction
**Question**: Found references to 10.41 IP addresses in vault scripts. Should we update these to 10.101 to match vault.lab.thewortmans.org?

**Decision**: Update all script references from 10.41 to 10.101. Only update the scripts themselves, not documentation files.

**Files Affected**:
- vault/scripts/01-initialize-vault.sh
- vault/scripts/02-unseal-vault.sh
- vault/scripts/03-configure-vault.sh
- vault/scripts/04-rotate-credentials.sh

#### 2. Git History Sanitization Strategy
**Question**: For sanitizing git history of exposed secrets, should we create an automated script OR detailed step-by-step instructions OR both?

**Decision**: Create BOTH - automated script AND detailed step-by-step instructions with explanations.

**Rationale**: Provides flexibility for different user comfort levels and serves as educational resource for understanding git history rewriting.

**Deliverables**:
- Automated script: `scripts/sanitize-git-history.sh`
- Documentation: `docs/SANITIZING-GIT-HISTORY.md`

#### 3. README.md Location and Strategy
**Question**: Should we create new README.md at root using docs/README.md as reference, or take a different approach?

**Decision**: Create a new README.md at repository root using docs/README.md as reference material. User will delete the original docs/README.md later.

**Rationale**: Root-level README.md is GitHub standard and provides immediate project introduction to visitors.

#### 4. Docker-Compose Files Handling
**Question**: What about docker-compose.yml files (appear to be new work)? Include in sanitization or handle separately?

**Decision**: Just add docker-compose files to .gitignore. Do NOT remove from git history.

**Rationale**: Files are relatively new and don't contain critical historical secret exposure issues.

**Implementation**: Add `docker-compose*.yml` pattern to .gitignore

#### 5. Vault Secret Organization Structure
**Question**: Do you have preferences for organizing secrets in Vault (e.g., by service, by environment, by type)?

**Decision**: No user preference specified - use HashiCorp best practices for Vault secret organization.

**Implementation Strategy**:
- Organize by logical service boundaries (kubernetes/, terraform/, ansible/, elasticsearch/)
- Use consistent path structures (service/environment/secret-name)
- Follow principle of least privilege for access policies
- Document the chosen structure clearly

#### 6. Documentation Files Organization
**Question**: Should detailed guides be kept under docs/ with links from main README, or different structure?

**Decision**: Detailed guides under docs/ directory, with links from the main README.md at root.

**Structure**:
```
README.md                          (Root - overview, quick start, links)
docs/
  VAULT-SETUP.md                   (Detailed Vault setup)
  SANITIZING-GIT-HISTORY.md        (Git history cleanup)
  DEPLOYMENT-GUIDE.md              (Full deployment process)
  SECRET-MANAGEMENT.md             (Vault usage patterns)
  CONTRIBUTING.md                  (If needed for public repo)
```

#### 7. CI/CD Automation Scope
**Question**: For CI/CD automation, which should be included: secret scanning/validation, Terraform plan/apply workflows, pre-commit hooks?

**Decision**: All of the above - comprehensive CI/CD implementation:
1. GitHub Actions for secret scanning and validation
2. Automated Terraform plan/apply workflows
3. Pre-commit hook automation

**Implementation Details**:
- `.github/workflows/secret-scan.yml` - Scan for accidentally committed secrets
- `.github/workflows/terraform-plan.yml` - Automated Terraform planning on PRs
- `.github/workflows/terraform-apply.yml` - Apply on merge to main
- `.pre-commit-config.yaml` - Local git hooks for pre-commit validation
- Setup script for pre-commit hooks

---

## Technical Architecture Decisions

### Vault Integration
- **Vault Server**: vault.lab.thewortmans.org (192.168.10.101)
- **Secret Storage**: All credentials migrated from code to Vault
- **Access Method**: Terraform Vault provider for infrastructure secrets
- **Authentication**: Appropriate auth methods per service (approle, kubernetes, etc.)

### Git History Sanitization
- **Tool Choice**: git-filter-repo (preferred over filter-branch)
- **Approach**: Remove sensitive files and rewrite history
- **Backup Strategy**: Create backup branch before sanitization
- **Target Files/Patterns**:
  - CCHS_PASSWORD
  - makerspace_es_api_key
  - ansible/inventory/vault (contains encrypted secrets)
  - Any files matching .gitignore secret patterns in history

### Configuration Management
- **Pattern**: All sensitive configs have .example versions
- **Real Configs**: Added to .gitignore, never committed
- **Examples**: Provide clear placeholders showing required structure

---

## Phasing Strategy

### Phase 1: Core Preparation (Primary Focus)
1. Update Vault script IP addresses (10.41 -> 10.101)
2. Complete Vault secret migration (all credentials)
3. Create git history sanitization tools (script + documentation)
4. Update .gitignore comprehensively
5. Create root README.md
6. Create detailed documentation in docs/
7. Verify all .example files are present and accurate
8. Test clean clone and setup process

### Phase 2: CI/CD Automation (Secondary)
1. GitHub Actions for secret scanning
2. Terraform plan/apply workflows
3. Pre-commit hooks configuration
4. Integration testing automation

**Rationale**: Core preparation must be complete and tested before repository goes public. CI/CD automation enhances the project but is not blocking for initial public release.

---

## Scope Boundaries

### In Scope
- Update Vault scripts to correct IP (10.101)
- Complete secret migration to Vault
- Git history sanitization (automated + manual docs)
- Comprehensive .gitignore updates
- Root-level README.md creation
- Detailed setup documentation (docs/)
- Example configuration files
- CI/CD automation (secret scanning, Terraform workflows, pre-commit hooks)
- Testing clean clone and setup

### Out of Scope
- Docker-compose history sanitization (adding to .gitignore only)
- Deleting original docs/README.md (user will do later)
- Actual Vault server provisioning (infrastructure assumed ready)
- Running git history sanitization (user will run script)
- Making repository public on GitHub (user action after verification)

---

## Security Considerations

### Pre-Public Checklist
Before making repository public, ensure:
- [ ] All secrets migrated to Vault
- [ ] Git history sanitized and verified clean
- [ ] .gitignore comprehensive and tested
- [ ] No API keys, passwords, or tokens in any commit
- [ ] Example files don't contain real credentials
- [ ] Documentation doesn't expose internal network details unnecessarily

### Ongoing Security
- Secret scanning GitHub Action catches accidental commits
- Pre-commit hooks prevent local secret commits
- Regular Vault credential rotation via existing scripts
- Clear documentation on secret management practices

---

## Success Criteria

The repository will be ready for public distribution when:

1. **Security**: No secrets in current state or git history
2. **Usability**: Clear README and documentation enable others to clone and deploy
3. **Maintainability**: CI/CD automation reduces manual validation overhead
4. **Professionalism**: Well-organized, documented, and follows infrastructure-as-code best practices
5. **Testing**: Clean clone test succeeds with only example files

---

## Implementation Notes

### Priority Order
1. Security fixes (Vault scripts IP, secret migration verification)
2. Git history sanitization
3. Documentation (README, docs/)
4. CI/CD automation

### Testing Strategy
- Create fresh clone in temporary directory
- Attempt setup following only the documentation
- Verify no secrets are required from git history
- Confirm all .example files work as templates

### Rollback Plan
- Maintain backup branch before history sanitization
- Keep private backup of repository in current state
- Document recovery process if issues found post-sanitization

---

## Existing Code to Reference

No similar existing features were identified for reference in this codebase. This is a unique infrastructure security and documentation enhancement project.

---

## Visual Assets

No visual assets were provided for this specification.

---

## Notes for Implementation

- Vault scripts need IP address updates across all four script files
- Git history sanitization is sensitive - provide both automation and manual process
- Documentation should be comprehensive enough for external users unfamiliar with this homelab
- CI/CD phase can be implemented after core work is verified working
- Consider creating a CONTRIBUTING.md if expecting external contributions
