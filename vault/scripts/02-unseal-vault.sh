#!/bin/bash
#
# Vault Unseal Script
# This script unseals Vault using stored unseal keys
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

VAULT_ADDR="${VAULT_ADDR:-https://192.168.10.101:8200}"
VAULT_SKIP_VERIFY="${VAULT_SKIP_VERIFY:-true}"
SECRETS_DIR="${HOME}/.vault-secrets"

export VAULT_ADDR
export VAULT_SKIP_VERIFY

echo -e "${BLUE}=== Vault Unseal Utility ===${NC}\n"

# Check Vault status
echo -e "${GREEN}Checking Vault status...${NC}"
if vault status 2>&1 | grep -q "Sealed.*false"; then
    echo -e "${GREEN}✓ Vault is already unsealed${NC}"
    vault status
    exit 0
fi

echo -e "${YELLOW}Vault is sealed. Enter 3 unseal keys to unseal.${NC}\n"

# Option 1: Manual entry
echo -e "${BLUE}Enter unseal keys manually:${NC}"
vault operator unseal
vault operator unseal
vault operator unseal

echo -e "\n${GREEN}✓ Vault unsealed successfully!${NC}"
vault status
