#!/bin/bash
#
# Vault Initialization Script
# This script initializes a new Vault instance and securely stores the unseal keys
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

VAULT_ADDR="${VAULT_ADDR:-https://vault.lab.thewortmans.org:8200}"
VAULT_SKIP_VERIFY="${VAULT_SKIP_VERIFY:-true}"
SECRETS_DIR="${HOME}/.vault-secrets"

echo -e "${BLUE}=== HashiCorp Vault Initialization ===${NC}\n"

# Check if vault CLI is installed
if ! command -v vault &> /dev/null; then
    echo -e "${RED}Error: vault CLI not found${NC}"
    echo "Install with: brew install vault (macOS) or apt install vault (Ubuntu)"
    exit 1
fi

# Set Vault address
export VAULT_ADDR
export VAULT_SKIP_VERIFY

echo -e "${YELLOW}Vault Address: ${VAULT_ADDR}${NC}"

# Check Vault status
echo -e "\n${GREEN}Checking Vault status...${NC}"
if ! vault status 2>&1 | grep -q "Initialized.*false"; then
    echo -e "${YELLOW}Vault appears to already be initialized.${NC}"
    echo -e "Current status:"
    vault status || true
    echo -e "\n${RED}If you need to re-initialize, you must first reset Vault.${NC}"
    echo -e "${RED}WARNING: This will destroy all existing data!${NC}"
    exit 1
fi

# Create secure directory for secrets
echo -e "\n${GREEN}Creating secure directory for secrets...${NC}"
mkdir -p "${SECRETS_DIR}"
chmod 700 "${SECRETS_DIR}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
INIT_FILE="${SECRETS_DIR}/vault-init-${TIMESTAMP}.txt"

echo -e "\n${YELLOW}Initializing Vault with 5 key shares and threshold of 3...${NC}"
vault operator init \
    -key-shares=5 \
    -key-threshold=3 \
    -format=json > "${INIT_FILE}.json"

# Extract keys and token
UNSEAL_KEY_1=$(jq -r '.unseal_keys_b64[0]' "${INIT_FILE}.json")
UNSEAL_KEY_2=$(jq -r '.unseal_keys_b64[1]' "${INIT_FILE}.json")
UNSEAL_KEY_3=$(jq -r '.unseal_keys_b64[2]' "${INIT_FILE}.json")
UNSEAL_KEY_4=$(jq -r '.unseal_keys_b64[3]' "${INIT_FILE}.json")
UNSEAL_KEY_5=$(jq -r '.unseal_keys_b64[4]' "${INIT_FILE}.json")
ROOT_TOKEN=$(jq -r '.root_token' "${INIT_FILE}.json")

# Create human-readable file
cat > "${INIT_FILE}" <<EOF
==============================================
Vault Initialization Data
Generated: ${TIMESTAMP}
==============================================

CRITICAL: Store these keys in a secure location!
You will need 3 of 5 keys to unseal Vault.

Unseal Key 1: ${UNSEAL_KEY_1}
Unseal Key 2: ${UNSEAL_KEY_2}
Unseal Key 3: ${UNSEAL_KEY_3}
Unseal Key 4: ${UNSEAL_KEY_4}
Unseal Key 5: ${UNSEAL_KEY_5}

Initial Root Token: ${ROOT_TOKEN}

==============================================
SECURITY RECOMMENDATIONS:
==============================================
1. Store each unseal key with a different person
2. Store keys in separate secure locations
3. Add to password manager (1Password, Bitwarden, etc.)
4. Never commit these to version control
5. Rotate root token after initial setup
6. Configure auto-unseal for production

==============================================
NEXT STEPS:
==============================================
1. Unseal Vault: ./02-unseal-vault.sh
2. Login to Vault: vault login ${ROOT_TOKEN}
3. Configure secrets: ./03-configure-vault.sh
4. Rotate credentials: ./04-rotate-credentials.sh
==============================================
EOF

# Secure the files
chmod 600 "${INIT_FILE}"
chmod 600 "${INIT_FILE}.json"

echo -e "\n${GREEN}✓ Vault initialized successfully!${NC}"
echo -e "\n${YELLOW}Initialization data saved to:${NC}"
echo -e "  ${INIT_FILE}"
echo -e "  ${INIT_FILE}.json"

echo -e "\n${RED}⚠️  CRITICAL SECURITY WARNING ⚠️${NC}"
echo -e "${RED}Store these keys securely NOW!${NC}"
echo -e "${RED}They cannot be recovered if lost!${NC}"

echo -e "\n${BLUE}Unseal keys and root token:${NC}"
echo -e "────────────────────────────────────────"
cat "${INIT_FILE}"
echo -e "────────────────────────────────────────"

echo -e "\n${YELLOW}Press Enter to continue and unseal Vault...${NC}"
read

# Automatically unseal Vault
echo -e "\n${GREEN}Unsealing Vault...${NC}"
vault operator unseal "${UNSEAL_KEY_1}"
vault operator unseal "${UNSEAL_KEY_2}"
vault operator unseal "${UNSEAL_KEY_3}"

echo -e "\n${GREEN}✓ Vault unsealed successfully!${NC}"
vault status

# Create .vault-token file for convenience
echo "${ROOT_TOKEN}" > "${HOME}/.vault-token"
chmod 600 "${HOME}/.vault-token"

echo -e "\n${GREEN}✓ Root token saved to ~/.vault-token${NC}"
echo -e "\n${YELLOW}You can now run: ./03-configure-vault.sh${NC}"
