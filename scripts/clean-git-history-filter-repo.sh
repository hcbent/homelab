#!/bin/bash
#
# Git History Cleaning Script (using git-filter-repo)
# This script removes all secrets from git history before making the repository public
#
# WARNINGS:
# - This is DESTRUCTIVE and rewrites git history
# - All collaborators will need to re-clone the repository
# - Make a backup before running this script
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║          WARNING: GIT HISTORY REWRITING SCRIPT                 ║${NC}"
echo -e "${RED}║                                                                ║${NC}"
echo -e "${RED}║  This script will PERMANENTLY remove secrets from git history ║${NC}"
echo -e "${RED}║  This is IRREVERSIBLE and will rewrite all commits            ║${NC}"
echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${YELLOW}Before proceeding, you MUST:${NC}"
echo -e "  1. Create a backup of this repository"
echo -e "  2. Ensure you're on a clean working directory"
echo -e "  3. Have git-filter-repo installed\n"

read -p "Continue with git history cleaning? (yes/no): " -r
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo -e "${RED}Aborting.${NC}"
    exit 1
fi

# Check if git-filter-repo is installed
if ! command -v git-filter-repo &> /dev/null; then
    echo -e "${RED}Error: git-filter-repo is not installed${NC}"
    echo -e "${YELLOW}Install it with: brew install git-filter-repo${NC}"
    exit 1
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo -e "${RED}Error: You have uncommitted changes${NC}"
    echo -e "${YELLOW}Please commit or stash your changes first${NC}"
    exit 1
fi

echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 1: Create backup${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

BACKUP_DIR="${REPO_DIR}_backup_$(date +%Y%m%d_%H%M%S)"
echo -e "Creating backup at: ${GREEN}${BACKUP_DIR}${NC}"
cp -r "$REPO_DIR" "$BACKUP_DIR"
echo -e "${GREEN}✓ Backup created${NC}\n"

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 2: Remove secret files from history${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

# Create paths file for files to remove
cat > /tmp/paths-to-remove.txt <<'EOF'
CCHS_PASSWORD
makerspace_es_api_key
deploy-and-setup.sh
tf-aliases.sh
CLAUDE.md
DEPLOYMENT-GUIDE.md
ansible/inventory/cchs
ansible/inventory/cchstest
ansible/inventory/deepfreeze
ansible/inventory/lab
ansible/inventory/monitoring
k8s/lab-cluster/aws_secret.yaml
k8s/freenas-storageclass.yaml
EOF

echo -e "${YELLOW}Removing the following files from all git history:${NC}"
cat /tmp/paths-to-remove.txt | while read line; do
    echo -e "  - $line"
done
echo ""

# Remove files from history
while IFS= read -r filepath; do
    if [ -n "$filepath" ]; then
        echo -e "Removing: ${YELLOW}$filepath${NC}"
        git filter-repo --path "$filepath" --invert-paths --force
    fi
done < /tmp/paths-to-remove.txt

rm /tmp/paths-to-remove.txt

echo -e "${GREEN}✓ Files removed from history${NC}\n"

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 3: Replace sensitive text patterns${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

# Create replacement file for sensitive patterns
# Format: literal:OLD_TEXT==>NEW_TEXT or regex:PATTERN==>REPLACEMENT
cat > /tmp/secrets-to-replace.txt <<'EOF'
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
***REMOVED***==>***REMOVED***
EOF

echo -e "${YELLOW}Replacing sensitive text patterns in git history...${NC}"
git filter-repo --replace-text /tmp/secrets-to-replace.txt --force

rm /tmp/secrets-to-replace.txt

echo -e "${GREEN}✓ Sensitive text patterns replaced${NC}\n"

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                   HISTORY CLEANING COMPLETE                    ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${YELLOW}Next steps:${NC}"
echo -e "  1. Review the changes with: ${BLUE}git log --oneline${NC}"
echo -e "  2. Add back the remote: ${BLUE}git remote add origin git@github.com:wortmanb/homelab.git${NC}"
echo -e "  3. Force push to remote: ${RED}git push origin --force --all${NC}"
echo -e "  4. Force push tags: ${RED}git push origin --force --tags${NC}"
echo -e "  5. All collaborators must re-clone the repository\n"

echo -e "${YELLOW}NOTE: git-filter-repo removes the remote origin for safety.${NC}"
echo -e "${YELLOW}You must add it back before pushing.${NC}\n"

echo -e "${GREEN}Backup location: ${BACKUP_DIR}${NC}\n"
