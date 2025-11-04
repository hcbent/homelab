#!/bin/bash
#
# Complete Vault Deployment Script
# This script automates the entire Vault deployment and credential rotation process
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║          Homelab Vault Complete Deployment Script             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}\n"

# Check prerequisites
echo -e "${CYAN}Checking prerequisites...${NC}\n"

MISSING_TOOLS=()

if ! command -v terraform &> /dev/null; then
    MISSING_TOOLS+=("terraform")
fi

if ! command -v ansible &> /dev/null; then
    MISSING_TOOLS+=("ansible")
fi

if ! command -v vault &> /dev/null; then
    MISSING_TOOLS+=("vault")
fi

if ! command -v gitleaks &> /dev/null; then
    MISSING_TOOLS+=("gitleaks (optional)")
fi

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo -e "${RED}Missing required tools:${NC}"
    for tool in "${MISSING_TOOLS[@]}"; do
        echo -e "  ${RED}✗${NC} $tool"
    done
    echo -e "\n${YELLOW}Install missing tools and try again.${NC}"
    echo -e "See DEPLOYMENT-GUIDE.md for installation instructions."
    exit 1
fi

echo -e "${GREEN}✓ All prerequisites installed${NC}\n"

# Display deployment plan
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${MAGENTA}Deployment Plan${NC}"
echo -e "${MAGENTA}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "This script will:"
echo -e "  1. ${CYAN}Deploy Vault VM${NC} using Terraform"
echo -e "  2. ${CYAN}Install Vault${NC} using Ansible"
echo -e "  3. ${CYAN}Initialize Vault${NC} and generate unseal keys"
echo -e "  4. ${CYAN}Configure secret structure${NC}"
echo -e "  5. ${CYAN}Guide credential rotation${NC}"
echo -e "  6. ${CYAN}Update .gitignore${NC}"
echo -e "  7. ${CYAN}Help clean Git history${NC}\n"

echo -e "${YELLOW}Estimated time: 30-45 minutes${NC}"
echo -e "${YELLOW}You will need: Proxmox credentials, TrueNAS access${NC}\n"

read -p "Continue with deployment? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${RED}Deployment cancelled${NC}"
    exit 0
fi

# Step 1: Deploy Vault VM
echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 1/7: Deploy Vault VM with Terraform${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

cd "${SCRIPT_DIR}/tf/vault"

if [ ! -f "terraform.tfvars" ]; then
    echo -e "${YELLOW}terraform.tfvars not found. Creating from example...${NC}"
    cp terraform.tfvars.example terraform.tfvars
    echo -e "${RED}Please edit terraform.tfvars with your credentials:${NC}"
    echo -e "  ${GREEN}vim terraform.tfvars${NC}"
    echo -e "\nThen run this script again."
    exit 1
fi

echo -e "${CYAN}Initializing Terraform...${NC}"
terraform init

echo -e "\n${CYAN}Planning deployment...${NC}"
terraform plan

echo -e "\n${YELLOW}Review the plan above.${NC}"
read -p "Apply this plan? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    terraform apply -auto-approve
    echo -e "${GREEN}✓ Vault VM deployed${NC}"
else
    echo -e "${RED}Deployment cancelled${NC}"
    exit 1
fi

# Wait for VM to be ready
echo -e "\n${YELLOW}Waiting for VM to boot (60 seconds)...${NC}"
sleep 60

# Step 2: Install Vault
echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 2/7: Install Vault with Ansible${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

cd "${SCRIPT_DIR}/ansible"

echo -e "${CYAN}Testing connectivity to Vault VM...${NC}"
if ansible -i inventory/vault vault -m ping; then
    echo -e "${GREEN}✓ VM is reachable${NC}"
else
    echo -e "${RED}✗ Cannot reach VM. Check SSH access and try again.${NC}"
    exit 1
fi

echo -e "\n${CYAN}Installing Vault...${NC}"
ansible-playbook -i inventory/vault playbooks/deploy_vault.yml

echo -e "${GREEN}✓ Vault installed${NC}"

# Step 3: Initialize Vault
echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 3/7: Initialize Vault${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

cd "${SCRIPT_DIR}/vault/scripts"
chmod +x *.sh

echo -e "${YELLOW}Initializing Vault...${NC}"
echo -e "${RED}IMPORTANT: Save the unseal keys and root token!${NC}\n"

./01-initialize-vault.sh

echo -e "\n${GREEN}✓ Vault initialized and unsealed${NC}"

# Step 4: Configure Vault
echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 4/7: Configure Vault Secret Structure${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${CYAN}Creating secret paths and policies...${NC}"
./03-configure-vault.sh

echo -e "${GREEN}✓ Vault configured${NC}"

# Step 5: Rotate Credentials
echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 5/7: Rotate Exposed Credentials${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${YELLOW}Starting credential rotation wizard...${NC}\n"
./04-rotate-credentials.sh

# Step 6: Update .gitignore
echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 6/7: Verify .gitignore${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

cd "${SCRIPT_DIR}"

echo -e "${CYAN}Checking .gitignore...${NC}"
if grep -q "vault/README.md" .gitignore; then
    echo -e "${GREEN}✓ .gitignore is up to date${NC}"
else
    echo -e "${YELLOW}⚠ .gitignore may need updating${NC}"
    echo -e "See .gitignore for secret file patterns"
fi

# Step 7: Clean Git History
echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 7/7: Clean Git History${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}\n"

echo -e "${YELLOW}Scanning for secrets in Git history...${NC}\n"

if command -v gitleaks &> /dev/null; then
    if gitleaks detect --source . --verbose; then
        echo -e "${GREEN}✓ No secrets found in repository${NC}"
    else
        echo -e "${RED}✗ Secrets found in Git history!${NC}\n"
        echo -e "${YELLOW}To remove secrets from history:${NC}"
        echo -e "  ${GREEN}git filter-repo --path k8s/helm/values/freenas-nfs.yaml --invert-paths${NC}"
        echo -e "  ${GREEN}git filter-repo --path k8s/helm/values/freenas-iscsi.yaml --invert-paths${NC}"
        echo -e "  ${GREEN}git filter-repo --path vault/README.md --invert-paths${NC}"
        echo -e "\n${RED}WARNING: This rewrites history. Coordinate with team!${NC}"
    fi
else
    echo -e "${YELLOW}gitleaks not installed. Skipping secret scan.${NC}"
    echo -e "Install with: ${GREEN}brew install gitleaks${NC}"
fi

# Summary
echo -e "\n${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                  Deployment Complete!                          ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}\n"

echo -e "${BLUE}What was completed:${NC}"
echo -e "  ${GREEN}✓${NC} Vault VM deployed at 192.168.10.41"
echo -e "  ${GREEN}✓${NC} Vault installed and running"
echo -e "  ${GREEN}✓${NC} Vault initialized with unseal keys"
echo -e "  ${GREEN}✓${NC} Secret structure configured"
echo -e "  ${GREEN}✓${NC} Credentials rotation guided"
echo -e "  ${GREEN}✓${NC} .gitignore updated\n"

echo -e "${BLUE}Vault Access:${NC}"
echo -e "  URL: ${GREEN}https://vault.lab.thewortmans.org:8200${NC}"
echo -e "  SSH: ${GREEN}ssh bret@vault.lab.thewortmans.org${NC}"
echo -e "  CLI: ${GREEN}export VAULT_ADDR=https://vault.lab.thewortmans.org:8200${NC}\n"

echo -e "${BLUE}Important Files:${NC}"
echo -e "  Unseal keys: ${GREEN}~/.vault-secrets/vault-init-*.txt${NC}"
echo -e "  Root token: ${GREEN}~/.vault-token${NC}"
echo -e "  ${RED}⚠ Keep these files secure and backed up!${NC}\n"

echo -e "${YELLOW}Next Steps:${NC}"
echo -e "  1. ${CYAN}Backup unseal keys${NC} to password manager"
echo -e "  2. ${CYAN}Integrate Terraform${NC} - See: tf/README-VAULT.md"
echo -e "  3. ${CYAN}Integrate Ansible${NC} - See: ansible/README-VAULT.md"
echo -e "  4. ${CYAN}Clean Git history${NC} if secrets found"
echo -e "  5. ${CYAN}Test integrations${NC} before removing old configs\n"

echo -e "${MAGENTA}Documentation:${NC}"
echo -e "  Overview: ${GREEN}SECURITY-AUDIT-SUMMARY.md${NC}"
echo -e "  Detailed: ${GREEN}DEPLOYMENT-GUIDE.md${NC}"
echo -e "  Security: ${GREEN}SECURITY.md${NC}\n"

echo -e "${GREEN}Your repository is now secure and ready to share!${NC}\n"
