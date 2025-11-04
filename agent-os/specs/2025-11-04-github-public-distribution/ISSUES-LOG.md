# Issues Log - Pre-Public Distribution Testing
**Generated**: 2025-11-04
**Source**: Task Group 7 Testing
**Status**: BLOCKERS PRESENT - Cannot Make Public

---

## Summary Statistics

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 3 | 🔴 BLOCKING |
| HIGH | 2 | 🟠 SHOULD FIX |
| MEDIUM | 5 | 🟡 RECOMMENDED |
| LOW | 3 | 🟢 OPTIONAL |
| **TOTAL** | **13** | - |

---

## CRITICAL Issues (BLOCKING)

### CRITICAL-1: Secret Files Tracked in Git
**ID**: CRIT-001
**Severity**: CRITICAL 🔴
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.5)
**Blocking**: YES - Cannot make public with active secrets

**Description**:
Two files containing actual secrets are tracked in the git repository and will be immediately visible if the repository is made public.

**Affected Files**:
- `CCHS_PASSWORD` - Contains plaintext password: `***REMOVED***`
- `makerspace_es_api_key` - Contains base64 API key: `***REMOVED***`

**Evidence**:
```bash
$ git ls-files | grep -E "(CCHS_PASSWORD|makerspace_es_api_key)"
CCHS_PASSWORD
makerspace_es_api_key

$ cat CCHS_PASSWORD
***REMOVED***

$ cat makerspace_es_api_key
***REMOVED***
```

**Impact**:
- HIGH: Immediate exposure of active credentials
- Elasticsearch cluster access compromised
- CCHS system access compromised

**Remediation Steps**:
1. Remove files from working directory:
   ```bash
   rm CCHS_PASSWORD makerspace_es_api_key
   git rm CCHS_PASSWORD makerspace_es_api_key
   git commit -m "Remove secret files before public release"
   ```

2. Add to .gitignore (explicit patterns):
   ```
   CCHS_PASSWORD
   makerspace_es_api_key
   ```

3. Rotate credentials immediately:
   - Change CCHS_PASSWORD in target system
   - Regenerate makerspace_es_api_key in Elasticsearch
   - Store new credentials in Vault only

4. Update Vault with new credentials:
   ```bash
   vault kv put secret/homelab/elasticsearch/cchs/credentials password="NEW_PASSWORD"
   vault kv put secret/homelab/elasticsearch/makerspace/credentials api_key="NEW_API_KEY"
   ```

5. Execute git history sanitization (see CRITICAL-2)

**Assigned To**: Repository Owner
**Priority**: P0 (Highest)
**Estimated Effort**: 30 minutes (removal) + credential rotation time
**Dependencies**: None
**Related Issues**: CRITICAL-2, HIGH-2

---

### CRITICAL-2: Password "***REMOVED***" in Git History
**ID**: CRIT-002
**Severity**: CRITICAL 🔴
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.5)
**Blocking**: YES - Historical secret exposure

**Description**:
The password "***REMOVED***" appears in 15 commits spanning from June 22, 2025 to November 4, 2025 (current HEAD). Even after removing from current state, this password will be accessible to anyone cloning the repository.

**Affected Commits**:
```
9e9ab2b - Complete Phase 1 tasks (Nov 4, 2025)
9a9b1d0 - Preparing to make this public (Nov 4, 2025)
17b60f7 - TF and ansible updates (Oct 20, 2025)
ad3d43c - Initial version of cerebro deployment (Oct 12, 2025)
1e96e51 - Ansible updates (Oct 10, 2025)
32ac535 - Added CCHS app setup (Oct 6, 2025)
e78c5d4 - Encryption and secrets for terraform (Sep 26, 2025)
8f20822 - Latest updates after cluster upgrades (Sep 25, 2025)
f054a6f - Update config (Sep 13, 2025)
be990db - Support files (Sep 8, 2025)
c9bb4e8 - Updating pihole to helm (Jul 25, 2025)
7e5d18d - Media-related files (Jul 6, 2025)
3369b7a - Latest updates (Jun 28, 2025)
2716d2c - Updating before cluster rebuild (Jun 27, 2025)
5d96973 - Updating to latest (Jun 22, 2025)
```

**Impact**:
- HIGH: Password exposed in history is effectively compromised
- System using this password is at risk
- Password cannot be considered secret after public release

**Remediation Steps**:
1. Identify files containing "***REMOVED***":
   ```bash
   git log -S "***REMOVED***" --all --name-only --format="%H %s" | tee benm1les-files.txt
   ```

2. Review sanitization script includes these files:
   ```bash
   cat scripts/sanitize-git-history.sh
   ```

3. Update script if needed to remove files containing this password

4. Run sanitization in dry-run mode:
   ```bash
   ./scripts/sanitize-git-history.sh --dry-run
   ```

5. Review dry-run output carefully

6. Execute sanitization (DESTRUCTIVE):
   ```bash
   ./scripts/sanitize-git-history.sh
   ```

7. Force-push sanitized history:
   ```bash
   git push --force --all
   git push --force --tags
   ```

8. Rotate "***REMOVED***" password immediately:
   - Change password in all systems using it
   - Store new password in Vault
   - Verify old password no longer works

9. Notify any collaborators:
   - All must re-clone repository
   - All must purge local copies of old history

**Assigned To**: Repository Owner
**Priority**: P0 (Highest)
**Estimated Effort**: 2-3 hours (sanitization + verification)
**Dependencies**: CRITICAL-1 must be resolved first
**Related Issues**: CRITICAL-3, MEDIUM-4

**⚠️ WARNING**: This is a destructive operation. Backup branch will be created automatically.

---

### CRITICAL-3: Cerebro Password in Git History
**ID**: CRIT-003
**Severity**: CRITICAL 🔴
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.5)
**Blocking**: YES - Historical secret exposure

**Description**:
The Cerebro password "***REMOVED***" appears in 2 commits. This password will be accessible to anyone cloning the repository.

**Affected Commits**:
```
9e9ab2b - Complete Phase 1 tasks (Nov 4, 2025)
0747af6 - Updating account info (Aug 7, 2025)
```

**Impact**:
- MEDIUM-HIGH: Cerebro UI password compromised
- Read access to Elasticsearch cluster metadata

**Remediation Steps**:
1. Same process as CRITICAL-2
2. Ensure sanitization script removes files containing "***REMOVED***"
3. Rotate Cerebro password:
   ```bash
   # Update Cerebro configuration
   # Store new password in Vault
   vault kv put secret/homelab/elasticsearch/cerebro password="NEW_PASSWORD"
   ```

**Assigned To**: Repository Owner
**Priority**: P0 (Highest)
**Estimated Effort**: Included in CRITICAL-2 sanitization
**Dependencies**: CRITICAL-2 (same sanitization process)
**Related Issues**: CRITICAL-2

---

## HIGH Priority Issues

### HIGH-1: Config Files with Secrets in History
**ID**: HIGH-001
**Severity**: HIGH 🟠
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.5)
**Blocking**: NO (but should fix before public)

**Description**:
Real configuration files with potential secrets exist in git history. These files are currently gitignored (won't be committed again) but historical versions may contain credentials.

**Affected Files**:
- `k8s/helm/values/freenas-nfs.yaml` - 3 commits in history
- `k8s/helm/values/freenas-iscsi.yaml` - 4 commits in history

**Commits**:
```
freenas-nfs.yaml:
- 9e9ab2b (Nov 4, 2025)
- 2716d2c (Jun 27, 2025)
- cefef15 (Jun 26, 2025)

freenas-iscsi.yaml:
- 9e9ab2b (Nov 4, 2025)
- 3369b7a (Jun 28, 2025)
- 2716d2c (Jun 27, 2025)
- cefef15 (Jun 26, 2025)
```

**Current Status**:
- ✅ Files are gitignored
- ✅ Files exist in current state with real config (for local use)
- ❌ Files accessible in git history

**Impact**:
- MEDIUM-HIGH: TrueNAS API keys may be in historical versions
- SSH passwords may be in historical versions
- NFS/iSCSI configuration details exposed

**Remediation Steps**:
1. Review historical versions for secrets:
   ```bash
   git log --all -p -- k8s/helm/values/freenas-nfs.yaml | grep -C 3 -i "password\|apikey\|api_key"
   git log --all -p -- k8s/helm/values/freenas-iscsi.yaml | grep -C 3 -i "password\|apikey\|api_key"
   ```

2. If secrets found, add files to sanitization script:
   ```bash
   # Edit scripts/sanitize-git-history.sh
   FILES_TO_REMOVE+=(
     "k8s/helm/values/freenas-nfs.yaml"
     "k8s/helm/values/freenas-iscsi.yaml"
   )
   ```

3. Execute sanitization (part of CRITICAL-2 process)

4. Rotate any credentials found in historical versions:
   - TrueNAS API key
   - TrueNAS root password
   - SSH keys

**Assigned To**: Repository Owner
**Priority**: P1 (High)
**Estimated Effort**: 1 hour (investigation + remediation)
**Dependencies**: Should be done with CRITICAL-2 sanitization
**Related Issues**: CRITICAL-2, MEDIUM-4

---

### HIGH-2: Incomplete .gitignore Pattern
**ID**: HIGH-002
**Severity**: HIGH 🟠
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.5)
**Blocking**: NO (but prevents future issues)

**Description**:
The .gitignore pattern `*_API_KEY` doesn't match the file `makerspace_es_api_key` because the pattern expects an underscore before API_KEY. This file could be accidentally committed again after removal.

**Current Patterns**:
```gitignore
*_PASSWORD
*_API_KEY
```

**Problem**:
- `CCHS_PASSWORD` ✅ Matches `*_PASSWORD`
- `makerspace_es_api_key` ❌ Does NOT match `*_API_KEY` (no underscore before API_KEY)

**Impact**:
- MEDIUM: Risk of re-committing secret file after removal
- Future developers might accidentally commit these files

**Remediation Steps**:
1. Add explicit patterns to .gitignore:
   ```gitignore
   # Specific secret files (explicit)
   CCHS_PASSWORD
   makerspace_es_api_key
   ELASTIC_PASSWORD
   MONITORING_PASSWORD

   # Pattern-based exclusions
   *_PASSWORD
   *_API_KEY
   *_api_key
   *_API_KEY_*
   *_SECRET
   *_TOKEN
   ```

2. Test patterns:
   ```bash
   touch TEST_PASSWORD makerspace_es_api_key CCHS_PASSWORD
   git status  # Should not show any of these files
   rm TEST_PASSWORD makerspace_es_api_key CCHS_PASSWORD
   ```

3. Commit updated .gitignore:
   ```bash
   git add .gitignore
   git commit -m "Improve .gitignore patterns for secret files"
   ```

**Assigned To**: Repository Owner
**Priority**: P1 (High)
**Estimated Effort**: 15 minutes
**Dependencies**: Should be done with CRITICAL-1
**Related Issues**: CRITICAL-1

---

## MEDIUM Priority Issues

### MEDIUM-1: README License Inconsistency
**ID**: MED-001
**Severity**: MEDIUM 🟡
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.2)
**Blocking**: NO

**Description**:
README.md states "License details to be determined" but LICENSE file exists with MIT License.

**Location**: README.md line 395

**Current Text**:
```markdown
## License

This project is open source. License details to be determined.
```

**Should Be**:
```markdown
## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
```

**Impact**:
- LOW-MEDIUM: Confusing for external users
- May discourage adoption/contribution

**Remediation**:
```bash
# Edit README.md line 395
sed -i '' 's/This project is open source. License details to be determined./This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details./' README.md
git add README.md
git commit -m "docs: Update README with correct license information"
```

**Assigned To**: Repository Owner
**Priority**: P2 (Medium)
**Estimated Effort**: 5 minutes
**Dependencies**: None

---

### MEDIUM-2: GitHub URL Placeholder
**ID**: MED-002
**Severity**: MEDIUM 🟡
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.2)
**Blocking**: NO

**Description**:
README.md line 82 contains placeholder GitHub URL that external users need to manually update.

**Location**: README.md line 82

**Current Text**:
```bash
git clone https://github.com/yourusername/homelab.git
cd homelab
```

**Should Be**:
```bash
git clone https://github.com/wortmanb/homelab.git
cd homelab
```

**Impact**:
- LOW-MEDIUM: Extra step for external users
- Copy-paste won't work

**Remediation**:
```bash
# Edit README.md line 82
sed -i '' 's|yourusername|wortmanb|' README.md
git add README.md
git commit -m "docs: Update README with correct GitHub repository URL"
```

**Assigned To**: Repository Owner
**Priority**: P2 (Medium)
**Estimated Effort**: 2 minutes
**Dependencies**: None

---

### MEDIUM-3: Missing Badges in README
**ID**: MED-003
**Severity**: MEDIUM 🟡
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.2)
**Blocking**: NO

**Description**:
Task 5.9 (Add badges) was not completed. README lacks professional badges for license, CI/CD status, etc.

**Location**: README.md (after title line)

**Recommended Badges**:
```markdown
# Homelab Infrastructure Platform

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Secret Scan](https://github.com/wortmanb/homelab/workflows/secret-scan/badge.svg)](https://github.com/wortmanb/homelab/actions)
[![Terraform Validation](https://github.com/wortmanb/homelab/workflows/terraform-plan/badge.svg)](https://github.com/wortmanb/homelab/actions)
```

**Impact**:
- LOW: Professional appearance
- Would show CI/CD status when implemented
- Industry standard practice

**Remediation**:
1. Add license badge immediately (can add others when CI/CD implemented)
2. Update README.md after title
3. Add CI/CD badges when Task Groups 8-9 are completed

**Assigned To**: Repository Owner
**Priority**: P2 (Medium)
**Estimated Effort**: 10 minutes (license badge now, CI/CD badges later)
**Dependencies**:
- License badge: None
- CI/CD badges: Task Groups 8-9 (Phase 2)

---

### MEDIUM-4: Sanitization Script Missing Files
**ID**: MED-004
**Severity**: MEDIUM 🟡
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.5)
**Blocking**: NO (but improves sanitization completeness)

**Description**:
The git history sanitization script doesn't include freenas YAML files that contain secrets in history.

**Location**: scripts/sanitize-git-history.sh

**Current Files List**:
```bash
FILES_TO_REMOVE=(
  "CCHS_PASSWORD"
  "makerspace_es_api_key"
  "ansible/inventory/vault"
)
```

**Should Include**:
```bash
FILES_TO_REMOVE=(
  "CCHS_PASSWORD"
  "makerspace_es_api_key"
  "ansible/inventory/vault"
  "k8s/helm/values/freenas-nfs.yaml"
  "k8s/helm/values/freenas-iscsi.yaml"
  "ELASTIC_PASSWORD"
  "MONITORING_PASSWORD"
)
```

**Impact**:
- MEDIUM: Incomplete history sanitization
- Secrets may remain in history after script execution

**Remediation**:
1. Edit scripts/sanitize-git-history.sh
2. Add missing files to FILES_TO_REMOVE array
3. Test in dry-run mode
4. Document changes

**Assigned To**: Repository Owner
**Priority**: P2 (Medium)
**Estimated Effort**: 20 minutes
**Dependencies**: Should be done before executing CRITICAL-2
**Related Issues**: CRITICAL-2, HIGH-1

---

### MEDIUM-5: Inconsistent Placeholder Values
**ID**: MED-005
**Severity**: MEDIUM 🟡
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.7)
**Blocking**: NO

**Description**:
Mix of placeholder formats across files causes user confusion: "VAULT_SECRET_REFERENCE", "CHANGE_ME_*", "changeme", etc.

**Examples Found**:
```yaml
# Ansible - Multiple formats
pihole_webpassword: "VAULT_SECRET_REFERENCE"
download_client_password: "CHANGE_ME_DOWNLOAD_PASSWORD"
password: "CHANGE_ME_LIDARR_DB_PASSWORD"
es_password: "{{ elasticsearch_password | default('changeme') }}"
```

**Recommended Standard**: "VAULT_SECRET_REFERENCE"

**Impact**:
- LOW-MEDIUM: User confusion
- Inconsistent documentation
- Harder to search/replace

**Remediation**:
1. Standardize all placeholders to "VAULT_SECRET_REFERENCE"
2. Update .example files
3. Update Ansible defaults
4. Update documentation examples
5. Create style guide for future contributions

**Files to Update**:
- ansible/roles/*/defaults/main.yml
- All .example files (review for consistency)
- docs/*.md (examples)

**Assigned To**: Repository Owner
**Priority**: P2 (Medium)
**Estimated Effort**: 1 hour
**Dependencies**: None

---

## LOW Priority Issues

### LOW-1: ansible/inventory/vault History Unknown
**ID**: LOW-001
**Severity**: LOW 🟢
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.5)
**Blocking**: NO

**Description**:
File `ansible/inventory/vault` appears in git history but hasn't been verified in current state. Need to check if it exists and contains secrets.

**Commits**:
- 9a9b1d0 (Nov 4, 2025)
- 5fda391 (Oct 29, 2025)

**Investigation Needed**:
```bash
# Check if file exists
ls -la ansible/inventory/vault

# Check history
git log --all -p -- ansible/inventory/vault

# Check for secrets
git show 9a9b1d0:ansible/inventory/vault | grep -i "password\|secret\|key"
```

**Impact**:
- UNKNOWN: Depends on file contents
- Could be CRITICAL if contains passwords

**Remediation**:
1. Investigate file (commands above)
2. If contains secrets, escalate to CRITICAL
3. If clean, close issue
4. If doesn't exist, verify included in sanitization script

**Assigned To**: Repository Owner
**Priority**: P3 (Low - but investigate soon)
**Estimated Effort**: 15 minutes investigation
**Dependencies**: None

---

### LOW-2: Ansible Default Password
**ID**: LOW-002
**Severity**: LOW 🟢
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.7)
**Blocking**: NO

**Description**:
Ansible role has default password that's not obvious as a placeholder.

**Location**: ansible/roles/elasticsearch/defaults/main.yml

**Current**:
```yaml
es_password: "{{ elasticsearch_password | default('changeme') }}"
```

**Recommended**:
```yaml
es_password: "{{ elasticsearch_password | default('VAULT_SECRET_REFERENCE') }}"
```

**Impact**:
- LOW: Potential misconfiguration if default used
- User might not notice needs to set password

**Remediation**:
1. Update default value to obvious placeholder
2. Add comment explaining Vault lookup required
3. Test playbooks still work with new default

**Assigned To**: Repository Owner
**Priority**: P3 (Low)
**Estimated Effort**: 5 minutes
**Dependencies**: Related to MEDIUM-5 (standardization)

---

### LOW-3: terraform.tfvars Gitignore Verification
**ID**: LOW-003
**Severity**: LOW 🟢
**Status**: OPEN
**Discovered**: 2025-11-04 (Task 7.6)
**Blocking**: NO

**Description**:
Need to verify all terraform.tfvars files (without .example) are properly gitignored.

**Files to Check**:
- tf/kubernetes/terraform.tfvars
- tf/lab/terraform.tfvars
- tf/vault/terraform.tfvars
- tf/home-apps/terraform.tfvars
- Any other terraform.tfvars files

**Verification**:
```bash
# Check if pattern exists
grep "terraform.tfvars" .gitignore

# Test with real file
cd tf/kubernetes
touch terraform.tfvars
git status  # Should NOT show file
rm terraform.tfvars
```

**Current .gitignore**:
Need to verify contains:
```gitignore
*.tfvars
!*.tfvars.example
terraform.tfvars
```

**Impact**:
- LOW: Potential future secret commit
- Best practice to explicitly exclude

**Remediation**:
1. Check current .gitignore patterns
2. Add explicit terraform.tfvars patterns if missing
3. Test with dummy files
4. Document in CONTRIBUTING.md

**Assigned To**: Repository Owner
**Priority**: P3 (Low)
**Estimated Effort**: 10 minutes
**Dependencies**: None

---

## Issue Tracking

### By Status
- **OPEN**: 13 issues
- **IN PROGRESS**: 0 issues
- **BLOCKED**: 0 issues
- **RESOLVED**: 0 issues

### By Priority
- **P0 (Critical)**: 3 issues
- **P1 (High)**: 2 issues
- **P2 (Medium)**: 5 issues
- **P3 (Low)**: 3 issues

### Blocking Public Release
- **YES**: 3 issues (CRITICAL-1, CRITICAL-2, CRITICAL-3)
- **NO**: 10 issues

---

## Remediation Plan

### Phase 1: CRITICAL (Must Complete Before Public) - Estimated 4 hours
1. **CRITICAL-1**: Remove secret files (30 min)
2. **HIGH-2**: Update .gitignore patterns (15 min)
3. **CRITICAL-2**: Git history sanitization (2 hours)
4. **CRITICAL-3**: Included in CRITICAL-2 (0 additional)
5. **Credential Rotation**: (1 hour)
   - ***REMOVED*** password
   - Cerebro password
   - CCHS_PASSWORD
   - makerspace_es_api_key
6. **Verification**: Re-run test suite (30 min)

**Total Phase 1**: ~4 hours

### Phase 2: HIGH (Should Complete Before Public) - Estimated 2 hours
1. **HIGH-1**: Review config files in history (1 hour)
2. **MEDIUM-1**: Fix README license (5 min)
3. **MEDIUM-2**: Fix README GitHub URL (2 min)
4. **MEDIUM-4**: Update sanitization script (20 min)
5. **LOW-1**: Investigate ansible/inventory/vault (15 min)

**Total Phase 2**: ~2 hours

### Phase 3: MEDIUM/LOW (Nice to Have) - Estimated 1.5 hours
1. **MEDIUM-3**: Add badges to README (10 min)
2. **MEDIUM-5**: Standardize placeholders (1 hour)
3. **LOW-2**: Fix Ansible default (5 min)
4. **LOW-3**: Verify tfvars gitignore (10 min)

**Total Phase 3**: ~1.5 hours

### Total Estimated Remediation Time: 7.5 hours

---

## Next Steps

### Immediate Actions (Today)
1. ⚠️ Do NOT make repository public
2. ⚠️ Review this issues log
3. ⚠️ Begin Phase 1 remediation
4. ⚠️ Start with CRITICAL-1 (fastest, prevents accidents)

### This Week
1. Complete all Phase 1 issues
2. Rotate all compromised credentials
3. Execute git history sanitization
4. Re-run test suite
5. Begin Phase 2 issues

### Before Public Release
1. All CRITICAL issues resolved ✅
2. All HIGH issues resolved ✅
3. Credential rotation complete ✅
4. Clean test suite results ✅
5. Backup created ✅
6. Rollback plan ready ✅

---

## Document Control

**Version**: 1.0
**Created**: 2025-11-04
**Last Updated**: 2025-11-04
**Author**: Claude Code (AI Agent)
**Status**: ACTIVE

**Related Documents**:
- TESTING-REPORT.md - Detailed test results
- docs/PRE-PUBLIC-CHECKLIST.md - Verification checklist
- docs/SANITIZING-GIT-HISTORY.md - Sanitization guide

**Change Log**:
- 2025-11-04: Initial creation from Task Group 7 testing

---

**END OF ISSUES LOG**
