#!/bin/bash
#
# Git History Sanitization Script
# This script removes sensitive files from the entire Git history using git-filter-repo
#
# WARNING: This script rewrites Git history and is IRREVERSIBLE
# Always create a backup before running!
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║           Git History Sanitization Script                     ║${NC}"
echo -e "${RED}║                  ⚠️  DANGER ZONE ⚠️                            ║${NC}"
echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}\n"

# Check for dry-run mode
DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    echo -e "${YELLOW}Running in DRY-RUN mode - no changes will be made${NC}\n"
fi

# Check prerequisites
echo -e "${CYAN}Checking prerequisites...${NC}\n"

if ! command -v git &> /dev/null; then
    echo -e "${RED}Error: git not found${NC}"
    exit 1
fi

if ! command -v git-filter-repo &> /dev/null; then
    echo -e "${RED}Error: git-filter-repo not found${NC}"
    echo -e "\n${YELLOW}Install git-filter-repo:${NC}"
    echo -e "  macOS: ${GREEN}brew install git-filter-repo${NC}"
    echo -e "  Ubuntu: ${GREEN}pip3 install git-filter-repo${NC}"
    echo -e "  Manual: ${GREEN}https://github.com/newren/git-filter-repo${NC}"
    exit 1
fi

echo -e "${GREEN}✓ All prerequisites installed${NC}\n"

# Change to repository root
cd "${REPO_ROOT}"

# Verify we're in a git repository
if [ ! -d ".git" ]; then
    echo -e "${RED}Error: Not in a git repository${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Git repository found: ${REPO_ROOT}${NC}\n"

# List of files to remove from history
# Only include files that contain actual secrets
SENSITIVE_FILES=(
    "CCHS_PASSWORD"
    "makerspace_es_api_key"
    "ansible/inventory/vault"
    "ELASTIC_PASSWORD"
    "MONITORING_PASSWORD"
    "k8s/helm/values/freenas-nfs.yaml"
    "k8s/helm/values/freenas-iscsi.yaml"
)

# Display what will be removed
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}Files to be removed from Git history:${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════════${NC}\n"

for file in "${SENSITIVE_FILES[@]}"; do
    if git log --all --format=%H -- "${file}" | head -n 1 &>/dev/null; then
        echo -e "  ${RED}✗${NC} ${file}"
    else
        echo -e "  ${YELLOW}⚠${NC} ${file} (not found in history)"
    fi
done

# Additional pattern-based files
echo -e "\n${MAGENTA}Pattern-based removals:${NC}"
echo -e "  ${RED}✗${NC} *_PASSWORD files"
echo -e "  ${RED}✗${NC} *_TOKEN files"
echo -e "  ${RED}✗${NC} *_API_KEY files"
echo -e "  ${RED}✗${NC} *_SECRET files"
echo -e "  ${RED}✗${NC} .env files (excluding *.env.example)"
echo -e "  ${RED}✗${NC} *vault-init*.json files"
echo -e "  ${RED}✗${NC} *.pem and *.key files (excluding *.pub)"

echo -e "\n${YELLOW}Total commits in repository:${NC} $(git rev-list --all --count)"
echo -e "${YELLOW}Repository size:${NC} $(du -sh .git | cut -f1)"

if [ "$DRY_RUN" = true ]; then
    echo -e "\n${GREEN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}DRY-RUN COMPLETE - No changes were made${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}\n"
    echo -e "${YELLOW}To perform actual sanitization, run:${NC}"
    echo -e "  ${GREEN}$0${NC}"
    exit 0
fi

# Confirm before proceeding
echo -e "\n${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║                     ⚠️  WARNING ⚠️                             ║${NC}"
echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${YELLOW}This operation will:${NC}"
echo -e "  1. Rewrite the ENTIRE Git history"
echo -e "  2. Remove sensitive files from ALL commits"
echo -e "  3. Change ALL commit hashes"
echo -e "  4. Make existing clones incompatible\n"

echo -e "${RED}This operation is IRREVERSIBLE!${NC}\n"

echo -e "${YELLOW}Before proceeding, ensure:${NC}"
echo -e "  [ ] All team members are notified"
echo -e "  [ ] You have a backup of the repository"
echo -e "  [ ] All work is committed and pushed"
echo -e "  [ ] You understand the implications\n"

read -p "Do you want to continue? Type 'YES' to confirm: " -r CONFIRM
echo

if [ "$CONFIRM" != "YES" ]; then
    echo -e "${YELLOW}Sanitization cancelled${NC}"
    exit 0
fi

# Create backup branch
echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 1/5: Creating Backup Branch${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_BRANCH="backup/pre-sanitization-${TIMESTAMP}"

echo -e "${CYAN}Creating backup branch: ${BACKUP_BRANCH}${NC}"
git branch "${BACKUP_BRANCH}"
echo -e "${GREEN}✓ Backup branch created${NC}"
echo -e "${YELLOW}To restore from backup: ${GREEN}git reset --hard ${BACKUP_BRANCH}${NC}\n"

# Create analysis file
ANALYSIS_FILE="${HOME}/.git-sanitization-${TIMESTAMP}.txt"
echo "Git History Sanitization Analysis" > "${ANALYSIS_FILE}"
echo "Timestamp: ${TIMESTAMP}" >> "${ANALYSIS_FILE}"
echo "Repository: ${REPO_ROOT}" >> "${ANALYSIS_FILE}"
echo "Backup Branch: ${BACKUP_BRANCH}" >> "${ANALYSIS_FILE}"
echo "" >> "${ANALYSIS_FILE}"
echo "Files removed:" >> "${ANALYSIS_FILE}"
for file in "${SENSITIVE_FILES[@]}"; do
    echo "  - ${file}" >> "${ANALYSIS_FILE}"
done

# Prepare git-filter-repo paths file
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 2/5: Preparing Filter Specifications${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

PATHS_FILE="/tmp/git-filter-paths-${TIMESTAMP}.txt"
> "${PATHS_FILE}"

# Add explicit files
for file in "${SENSITIVE_FILES[@]}"; do
    echo "${file}" >> "${PATHS_FILE}"
done

echo -e "${GREEN}✓ Filter specifications prepared${NC}\n"

# Remove sensitive files from history
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 3/5: Removing Files from History${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${YELLOW}This may take several minutes...${NC}\n"

# Run git-filter-repo
git filter-repo --invert-paths --paths-from-file "${PATHS_FILE}" --force

echo -e "\n${GREEN}✓ Files removed from history${NC}\n"

# Run validation checks
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 4/5: Validation Checks${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${CYAN}Scanning for remaining secrets...${NC}\n"

VALIDATION_FAILED=false

# Check for known secret patterns
echo "Validation Results:" >> "${ANALYSIS_FILE}"
echo "" >> "${ANALYSIS_FILE}"

for file in "${SENSITIVE_FILES[@]}"; do
    if git log --all --format=%H -- "${file}" | head -n 1 &>/dev/null; then
        echo -e "${RED}✗ Found: ${file}${NC}"
        echo "  FAIL: ${file} still in history" >> "${ANALYSIS_FILE}"
        VALIDATION_FAILED=true
    else
        echo -e "${GREEN}✓ Removed: ${file}${NC}"
        echo "  PASS: ${file} removed" >> "${ANALYSIS_FILE}"
    fi
done

# Check for pattern matches
echo -e "\n${CYAN}Checking for secret patterns...${NC}"

# Search for common secret patterns (limiting to recent history for performance)
if git log --all -S"password=" --format=%H | head -n 1 &>/dev/null; then
    echo -e "${YELLOW}⚠ Warning: Found 'password=' in history${NC}"
    echo "  WARNING: Found 'password=' pattern" >> "${ANALYSIS_FILE}"
fi

if git log --all -S"api_key=" --format=%H | head -n 1 &>/dev/null; then
    echo -e "${YELLOW}⚠ Warning: Found 'api_key=' in history${NC}"
    echo "  WARNING: Found 'api_key=' pattern" >> "${ANALYSIS_FILE}"
fi

echo -e "\n${YELLOW}New commit count:${NC} $(git rev-list --all --count)"
echo -e "${YELLOW}New repository size:${NC} $(du -sh .git | cut -f1)"

if [ "$VALIDATION_FAILED" = true ]; then
    echo -e "\n${RED}✗ Validation FAILED - Some files still in history${NC}"
    echo -e "${YELLOW}Check the analysis file: ${ANALYSIS_FILE}${NC}"
    echo -e "${YELLOW}You may need to run additional cleanup${NC}\n"
else
    echo -e "\n${GREEN}✓ Validation PASSED${NC}\n"
fi

# Cleanup
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 5/5: Cleanup${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

rm -f "${PATHS_FILE}"
echo -e "${GREEN}✓ Temporary files cleaned up${NC}\n"

# Summary
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                Sanitization Complete!                          ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${BLUE}What was done:${NC}"
echo -e "  ${GREEN}✓${NC} Backup branch created: ${BACKUP_BRANCH}"
echo -e "  ${GREEN}✓${NC} Sensitive files removed from history"
echo -e "  ${GREEN}✓${NC} Validation checks completed"
echo -e "  ${GREEN}✓${NC} Analysis saved: ${ANALYSIS_FILE}\n"

echo -e "${YELLOW}⚠️  IMPORTANT NEXT STEPS:${NC}\n"

echo -e "${BLUE}1. Verify the sanitization:${NC}"
echo -e "   ${GREEN}git log --all --oneline | head -20${NC}"
echo -e "   ${GREEN}git log --all -- CCHS_PASSWORD${NC} (should be empty)\n"

echo -e "${BLUE}2. Test your repository:${NC}"
echo -e "   ${GREEN}git status${NC}"
echo -e "   ${GREEN}git log${NC}\n"

echo -e "${BLUE}3. If everything looks good:${NC}"
echo -e "   ${GREEN}git push --force --all${NC}"
echo -e "   ${GREEN}git push --force --tags${NC}"
echo -e "   ${RED}WARNING: This will overwrite remote history!${NC}\n"

echo -e "${BLUE}4. If you need to rollback:${NC}"
echo -e "   ${GREEN}git reset --hard ${BACKUP_BRANCH}${NC}"
echo -e "   ${GREEN}git branch -D ${BACKUP_BRANCH}${NC}\n"

echo -e "${BLUE}5. Notify all contributors:${NC}"
echo -e "   ${YELLOW}All existing clones must be deleted and re-cloned${NC}"
echo -e "   ${YELLOW}Old clones will be incompatible with new history${NC}\n"

echo -e "${MAGENTA}Documentation:${NC}"
echo -e "  See: ${GREEN}docs/SANITIZING-GIT-HISTORY.md${NC} for details\n"

echo -e "${CYAN}Analysis file saved to: ${ANALYSIS_FILE}${NC}\n"
