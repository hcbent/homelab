#!/bin/bash
#
# Credential Rotation Script
# This script helps rotate all exposed credentials found in the security audit
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${RED}║          CRITICAL: CREDENTIAL ROTATION REQUIRED                ║${NC}"
echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${YELLOW}This script will guide you through rotating credentials that were${NC}"
echo -e "${YELLOW}exposed in your Git repository.${NC}\n"

echo -e "${RED}The following credentials MUST be rotated immediately:${NC}"
echo -e "  1. TrueNAS/FreeNAS root password"
echo -e "  2. TrueNAS/FreeNAS API key"
echo -e "  3. TrueNAS/FreeNAS SSH private key"
echo -e "  4. HashiCorp Vault unseal keys and root token\n"

read -p "Press Enter to continue..."

echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 1: Rotate TrueNAS/FreeNAS Credentials${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${YELLOW}Actions required on TrueNAS (https://192.168.2.24):${NC}"
echo -e "  1. Login to TrueNAS web interface"
echo -e "  2. Go to: ${GREEN}Accounts > Users > root > Edit${NC}"
echo -e "  3. Change the root password"
echo -e "  4. Save the new password securely\n"

read -p "Have you changed the root password? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}✓ Root password marked as rotated${NC}"
    read -p "Enter new root password (will be hidden): " -s NEW_ROOT_PASSWORD
    echo

    if command -v vault &> /dev/null && vault status &>/dev/null; then
        echo -e "\n${YELLOW}Storing in Vault...${NC}"
        vault kv put secret/homelab/freenas/credentials root_password="${NEW_ROOT_PASSWORD}"
        echo -e "${GREEN}✓ New password stored in Vault${NC}"
    else
        echo -e "${YELLOW}⚠ Vault not available. Save password manually.${NC}"
    fi
else
    echo -e "${RED}✗ Please rotate the root password before continuing${NC}"
fi

echo -e "\n${YELLOW}Rotating TrueNAS API Key:${NC}"
echo -e "  1. Go to: ${GREEN}API Keys${NC}"
echo -e "  2. Delete the old API key: ${RED}***REMOVED***${NC}"
echo -e "  3. Click ${GREEN}+ ADD${NC} to create a new API key"
echo -e "  4. Copy the new API key\n"

read -p "Have you created a new API key? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${GREEN}✓ API key marked as rotated${NC}"
    read -p "Enter new API key: " NEW_API_KEY

    if command -v vault &> /dev/null && vault status &>/dev/null; then
        echo -e "\n${YELLOW}Storing in Vault...${NC}"
        vault kv put secret/homelab/freenas/credentials api_key="${NEW_API_KEY}"
        echo -e "${GREEN}✓ New API key stored in Vault${NC}"
    else
        echo -e "${YELLOW}⚠ Vault not available. Save API key manually.${NC}"
    fi
else
    echo -e "${RED}✗ Please rotate the API key before continuing${NC}"
fi

echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 2: Generate New SSH Key for TrueNAS${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${YELLOW}Generating new SSH key pair...${NC}"
SSH_KEY_PATH="${HOME}/.ssh/truenas_ed25519"

if [ -f "${SSH_KEY_PATH}" ]; then
    echo -e "${YELLOW}Backing up existing key to ${SSH_KEY_PATH}.old${NC}"
    mv "${SSH_KEY_PATH}" "${SSH_KEY_PATH}.old"
    mv "${SSH_KEY_PATH}.pub" "${SSH_KEY_PATH}.pub.old"
fi

ssh-keygen -t ed25519 -f "${SSH_KEY_PATH}" -C "truenas-homelab-$(date +%Y%m%d)" -N ""

echo -e "${GREEN}✓ New SSH key generated${NC}"
echo -e "\nPublic key:"
cat "${SSH_KEY_PATH}.pub"

echo -e "\n${YELLOW}Configure on TrueNAS:${NC}"
echo -e "  1. SSH to TrueNAS: ${GREEN}ssh root@192.168.2.24${NC}"
echo -e "  2. Edit authorized_keys: ${GREEN}vi ~/.ssh/authorized_keys${NC}"
echo -e "  3. Remove the old ECDSA key"
echo -e "  4. Add the new public key shown above"
echo -e "  5. Save and test: ${GREEN}ssh -i ${SSH_KEY_PATH} root@192.168.2.24${NC}\n"

if command -v vault &> /dev/null && vault status &>/dev/null; then
    echo -e "${YELLOW}Storing private key in Vault...${NC}"
    vault kv put secret/homelab/freenas/ssh \
        private_key="$(cat ${SSH_KEY_PATH})" \
        public_key="$(cat ${SSH_KEY_PATH}.pub)"
    echo -e "${GREEN}✓ SSH keys stored in Vault${NC}"
fi

read -p "Press Enter when SSH key is configured on TrueNAS..."

echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 3: Re-initialize Vault (CRITICAL)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${RED}⚠️  WARNING: Your Vault unseal keys and root token were exposed!${NC}"
echo -e "${RED}⚠️  You MUST re-initialize Vault with new keys!${NC}\n"

echo -e "${YELLOW}Exposed keys that need rotation:${NC}"
echo -e "  Unseal Key 1: <REDACTED - Was exposed in git history>"
echo -e "  Unseal Key 2: <REDACTED - Was exposed in git history>"
echo -e "  ... (and 3 more keys)"
echo -e "  Root Token: <REDACTED - Was exposed in git history>\n"

echo -e "${RED}This requires:${NC}"
echo -e "  1. Exporting all current secrets from Vault"
echo -e "  2. Stopping Vault service"
echo -e "  3. Deleting Vault data directory"
echo -e "  4. Re-initializing Vault"
echo -e "  5. Re-importing all secrets\n"

echo -e "${YELLOW}If you have NOT yet deployed Vault, you can skip this.${NC}"
read -p "Do you need to rotate Vault credentials? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "\n${YELLOW}This will be handled when you run ./01-initialize-vault.sh${NC}"
    echo -e "${YELLOW}on your new Vault deployment.${NC}"
fi

echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 4: Update Configuration Files${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${YELLOW}The following files contain exposed secrets and should be removed:${NC}"
echo -e "  ${RED}✗${NC} k8s/helm/values/freenas-nfs.yaml"
echo -e "  ${RED}✗${NC} k8s/helm/values/freenas-iscsi.yaml"
echo -e "  ${RED}✗${NC} vault/README.md\n"

echo -e "${YELLOW}Template files have been created:${NC}"
echo -e "  ${GREEN}✓${NC} k8s/helm/values/freenas-nfs.yaml.example"
echo -e "  ${GREEN}✓${NC} k8s/helm/values/freenas-iscsi.yaml.example"
echo -e "  ${GREEN}✓${NC} vault/README.md.example\n"

read -p "Remove the files with exposed secrets? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if [ -f "k8s/helm/values/freenas-nfs.yaml" ]; then
        mv k8s/helm/values/freenas-nfs.yaml k8s/helm/values/freenas-nfs.yaml.backup
        echo -e "${GREEN}✓ Backed up freenas-nfs.yaml${NC}"
    fi

    if [ -f "k8s/helm/values/freenas-iscsi.yaml" ]; then
        mv k8s/helm/values/freenas-iscsi.yaml k8s/helm/values/freenas-iscsi.yaml.backup
        echo -e "${GREEN}✓ Backed up freenas-iscsi.yaml${NC}"
    fi

    if [ -f "vault/README.md" ]; then
        mv vault/README.md vault/README.md.backup
        echo -e "${GREEN}✓ Backed up vault/README.md${NC}"
    fi

    echo -e "\n${YELLOW}Backup files created with .backup extension${NC}"
    echo -e "${YELLOW}Review and delete these after confirming everything works${NC}"
fi

echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 5: Clean Git History${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${RED}⚠️  CRITICAL: Secrets are in your Git history!${NC}"
echo -e "${YELLOW}Even after removing files, they exist in previous commits.${NC}\n"

echo -e "${YELLOW}To completely remove secrets from Git history:${NC}"
echo -e "  ${GREEN}git filter-repo --path k8s/helm/values/freenas-nfs.yaml --invert-paths${NC}"
echo -e "  ${GREEN}git filter-repo --path k8s/helm/values/freenas-iscsi.yaml --invert-paths${NC}"
echo -e "  ${GREEN}git filter-repo --path vault/README.md --invert-paths${NC}\n"

echo -e "${RED}WARNING: This rewrites Git history!${NC}"
echo -e "  • Coordinate with all repository users"
echo -e "  • All users will need to re-clone the repository"
echo -e "  • Existing clones will be incompatible\n"

echo -e "${YELLOW}Install git-filter-repo:${NC}"
echo -e "  macOS: ${GREEN}brew install git-filter-repo${NC}"
echo -e "  Ubuntu: ${GREEN}apt install git-filter-repo${NC}\n"

echo -e "\n${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Credential Rotation Summary${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${BLUE}Checklist:${NC}"
echo -e "  [ ] Rotated TrueNAS root password"
echo -e "  [ ] Rotated TrueNAS API key"
echo -e "  [ ] Generated new SSH key for TrueNAS"
echo -e "  [ ] Configured new SSH key on TrueNAS"
echo -e "  [ ] Removed files with exposed secrets"
echo -e "  [ ] Planned Vault re-initialization"
echo -e "  [ ] Ready to clean Git history\n"

echo -e "${YELLOW}Next steps:${NC}"
echo -e "  1. Deploy Vault VM: ${GREEN}cd tf/vault && terraform apply${NC}"
echo -e "  2. Install Vault: ${GREEN}ansible-playbook -i inventory/vault playbooks/deploy_vault.yml${NC}"
echo -e "  3. Initialize Vault: ${GREEN}./vault/scripts/01-initialize-vault.sh${NC}"
echo -e "  4. Store all new credentials in Vault"
echo -e "  5. Update .gitignore to prevent future exposure"
echo -e "  6. Clean Git history with git-filter-repo\n"

echo -e "${GREEN}✓ Credential rotation guidance complete${NC}"
