#!/bin/bash
#
# Git History Cleaning Script
# This script removes all secrets from git history before making the repository public
#
# WARNINGS:
# - This is DESTRUCTIVE and rewrites git history
# - All collaborators will need to re-clone the repository
# - Make a backup before running this script
# - You MUST rotate all exposed credentials BEFORE pushing cleaned history
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
echo -e "  2. Rotate ALL exposed credentials"
echo -e "  3. Ensure you're on a clean working directory"
echo -e "  4. Have BFG Repo Cleaner installed (brew install bfg)\n"

read -p "Have you completed ALL prerequisites above? (yes/no): " -r
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo -e "${RED}Aborting. Please complete prerequisites first.${NC}"
    exit 1
fi

# Check if BFG is installed
if ! command -v bfg &> /dev/null; then
    echo -e "${RED}Error: BFG Repo Cleaner is not installed${NC}"
    echo -e "${YELLOW}Install it with: brew install bfg${NC}"
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

# List of files to completely remove from history
FILES_TO_DELETE=(
    "CCHS_PASSWORD"
    "makerspace_es_api_key"
    "deploy-and-setup.sh"
    "tf-aliases.sh"
    "CLAUDE.md"
    "DEPLOYMENT-GUIDE.md"
    "ansible/inventory/cchs"
    "ansible/inventory/cchstest"
    "ansible/inventory/deepfreeze"
    "ansible/inventory/lab"
    "k8s/lab-cluster/aws_secret.yaml"
    "k8s/freenas-storageclass.yaml"
)

echo -e "${YELLOW}Removing the following files from all git history:${NC}"
for file in "${FILES_TO_DELETE[@]}"; do
    echo -e "  - $file"
done
echo ""

for file in "${FILES_TO_DELETE[@]}"; do
    echo -e "Removing: ${YELLOW}$file${NC}"
    bfg --delete-files "$file" --no-blob-protection || true
done

echo -e "${GREEN}✓ Files removed from history${NC}\n"

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 3: Remove sensitive text patterns${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

# Create a text file with sensitive patterns to replace
cat > /tmp/secrets-to-replace.txt <<'EOF'
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
ki:s:[[@=Ag?QI`W2jMwkY:eqvrJ]JqoJyi2axj3ZvOv^/KavOT4ViJSv?6YY4[N
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
***REMOVED***
EOF

echo -e "${YELLOW}Replacing sensitive text patterns in git history...${NC}"
bfg --replace-text /tmp/secrets-to-replace.txt --no-blob-protection

rm /tmp/secrets-to-replace.txt

echo -e "${GREEN}✓ Sensitive text patterns replaced${NC}\n"

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 4: Clean up and expire reflogs${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${YELLOW}Running git reflog expire and garbage collection...${NC}"
git reflog expire --expire=now --all
git gc --prune=now --aggressive

echo -e "${GREEN}✓ Reflog expired and garbage collected${NC}\n"

echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 5: Verify secret removal${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${YELLOW}Running git log to check for removed files...${NC}"
REMAINING_SECRETS=0

for file in "${FILES_TO_DELETE[@]}"; do
    if git log --all --oneline -- "$file" 2>/dev/null | grep -q .; then
        echo -e "${RED}✗ File still in history: $file${NC}"
        REMAINING_SECRETS=$((REMAINING_SECRETS + 1))
    fi
done

if [ $REMAINING_SECRETS -eq 0 ]; then
    echo -e "${GREEN}✓ All secret files successfully removed from history${NC}\n"
else
    echo -e "${RED}⚠ Warning: Some files may still be in history${NC}\n"
fi

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                   HISTORY CLEANING COMPLETE                    ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${YELLOW}Next steps:${NC}"
echo -e "  1. Review the changes with: ${BLUE}git log --oneline${NC}"
echo -e "  2. Ensure all secrets have been removed"
echo -e "  3. Force push to remote: ${RED}git push origin --force --all${NC}"
echo -e "  4. Force push tags: ${RED}git push origin --force --tags${NC}"
echo -e "  5. All collaborators must re-clone the repository\n"

echo -e "${RED}⚠ CRITICAL: Have you rotated ALL exposed credentials?${NC}"
echo -e "${RED}   Cleaning git history is NOT enough - credentials must be rotated!${NC}\n"

echo -e "${GREEN}Backup location: ${BACKUP_DIR}${NC}\n"
