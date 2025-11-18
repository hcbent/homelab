#!/bin/bash
#
# Tailscale Auth Key Storage Script
# This script stores Tailscale auth keys in HashiCorp Vault for secure retrieval
# by Kubernetes deployments
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Vault configuration
VAULT_ADDR="${VAULT_ADDR:-https://192.168.10.101:8200}"
VAULT_SKIP_VERIFY="${VAULT_SKIP_VERIFY:-true}"
VAULT_PATH="secret/tailscale/auth-keys"

export VAULT_ADDR
export VAULT_SKIP_VERIFY

echo -e "${BLUE}=== Tailscale Auth Key Storage in Vault ===${NC}\n"

# Check if Vault is accessible
echo -e "${YELLOW}Checking Vault connectivity...${NC}"
if ! curl -s -k "${VAULT_ADDR}/v1/sys/health" > /dev/null 2>&1; then
    echo -e "${RED}Error: Cannot reach Vault at ${VAULT_ADDR}${NC}"
    echo -e "Please verify Vault is running and accessible."
    exit 1
fi
echo -e "${GREEN}✓ Vault is accessible${NC}\n"

# Check if authenticated to Vault
echo -e "${YELLOW}Checking Vault authentication...${NC}"
if ! vault token lookup &>/dev/null; then
    echo -e "${RED}Error: Not authenticated to Vault${NC}"
    echo -e "Please login first:"
    echo -e "  ${GREEN}export VAULT_ADDR=${VAULT_ADDR}${NC}"
    echo -e "  ${GREEN}export VAULT_SKIP_VERIFY=${VAULT_SKIP_VERIFY}${NC}"
    echo -e "  ${GREEN}vault login${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Authenticated to Vault${NC}\n"

# Check if KV v2 secrets engine is enabled
echo -e "${YELLOW}Checking KV secrets engine...${NC}"
if ! vault secrets list | grep -q "^secret/"; then
    echo -e "${RED}Error: KV secrets engine not enabled at 'secret/'${NC}"
    echo -e "Enable it with: ${GREEN}vault secrets enable -path=secret kv-v2${NC}"
    exit 1
fi
echo -e "${GREEN}✓ KV secrets engine enabled${NC}\n"

# Prompt for auth key
echo -e "${BLUE}Please enter your Tailscale auth key:${NC}"
echo -e "${YELLOW}The key should look like: tskey-auth-xxxxx-yyyyy${NC}"
read -sp "Auth Key: " AUTH_KEY
echo "" # New line after password input

# Validate auth key format (basic check)
if [[ ! "$AUTH_KEY" =~ ^tskey-auth- ]]; then
    echo -e "${RED}Error: Invalid auth key format${NC}"
    echo -e "Auth keys should start with 'tskey-auth-'"
    exit 1
fi

# Store in Vault
echo -e "\n${YELLOW}Storing auth key in Vault at ${VAULT_PATH}...${NC}"
if vault kv put "${VAULT_PATH}" auth_key="${AUTH_KEY}" created_by="$(whoami)" created_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")" &>/dev/null; then
    echo -e "${GREEN}✓ Auth key stored successfully${NC}\n"
else
    echo -e "${RED}Error: Failed to store auth key in Vault${NC}"
    exit 1
fi

# Verify storage
echo -e "${YELLOW}Verifying storage...${NC}"
if vault kv get "${VAULT_PATH}" &>/dev/null; then
    echo -e "${GREEN}✓ Auth key verified in Vault${NC}\n"
else
    echo -e "${RED}Error: Could not verify auth key storage${NC}"
    exit 1
fi

# Test retrieval (mask the actual key)
echo -e "${YELLOW}Testing retrieval from Vault...${NC}"
RETRIEVED_KEY=$(vault kv get -field=auth_key "${VAULT_PATH}" 2>/dev/null)
if [[ -n "$RETRIEVED_KEY" ]]; then
    # Mask most of the key for security
    MASKED_KEY="${RETRIEVED_KEY:0:15}...${RETRIEVED_KEY: -5}"
    echo -e "${GREEN}✓ Successfully retrieved: ${MASKED_KEY}${NC}\n"
else
    echo -e "${RED}Error: Could not retrieve auth key${NC}"
    exit 1
fi

# Display storage information
echo -e "${BLUE}Storage Information:${NC}"
echo -e "  Vault Address: ${GREEN}${VAULT_ADDR}${NC}"
echo -e "  Storage Path: ${GREEN}${VAULT_PATH}${NC}"
echo -e "  Key Field: ${GREEN}auth_key${NC}\n"

# Create Vault policy for Kubernetes access
echo -e "${YELLOW}Creating Vault policy for Kubernetes access...${NC}"

# Check if policy already exists
if vault policy read tailscale-k8s &>/dev/null; then
    echo -e "${YELLOW}  Policy 'tailscale-k8s' already exists, updating...${NC}"
fi

# Create policy file
cat > /tmp/tailscale-k8s-policy.hcl <<EOF
# Policy for Kubernetes to read Tailscale auth keys
path "secret/data/tailscale/auth-keys" {
  capabilities = ["read"]
}

path "secret/metadata/tailscale/auth-keys" {
  capabilities = ["read"]
}
EOF

# Write policy to Vault
if vault policy write tailscale-k8s /tmp/tailscale-k8s-policy.hcl &>/dev/null; then
    echo -e "${GREEN}✓ Vault policy 'tailscale-k8s' created/updated${NC}\n"
    rm /tmp/tailscale-k8s-policy.hcl
else
    echo -e "${RED}Error: Failed to create Vault policy${NC}"
    rm /tmp/tailscale-k8s-policy.hcl
    exit 1
fi

# Test policy
echo -e "${YELLOW}Testing Vault policy...${NC}"
if vault policy read tailscale-k8s &>/dev/null; then
    echo -e "${GREEN}✓ Policy is readable and active${NC}\n"
else
    echo -e "${RED}Error: Could not read policy${NC}"
    exit 1
fi

# Summary
echo -e "${GREEN}=== Setup Complete ===${NC}\n"
echo -e "${BLUE}Summary:${NC}"
echo -e "  ${GREEN}✓${NC} Tailscale auth key stored in Vault"
echo -e "  ${GREEN}✓${NC} Storage verified with successful retrieval"
echo -e "  ${GREEN}✓${NC} Vault policy 'tailscale-k8s' created for Kubernetes access"
echo -e "  ${GREEN}✓${NC} Ready for Kubernetes operator deployment\n"

echo -e "${YELLOW}Next Steps:${NC}"
echo -e "1. Note the storage path: ${GREEN}${VAULT_PATH}${NC}"
echo -e "2. Proceed to deploy Tailscale Kubernetes operator"
echo -e "3. Configure operator to read from this Vault path"
echo -e "4. Verify nodes appear in your tailnet\n"

echo -e "${YELLOW}To retrieve the auth key later:${NC}"
echo -e "  ${GREEN}vault kv get -field=auth_key ${VAULT_PATH}${NC}\n"

echo -e "${YELLOW}Security Notes:${NC}"
echo -e "  - Auth key is encrypted at rest in Vault"
echo -e "  - Only authenticated Vault users can access the key"
echo -e "  - Kubernetes pods will use service account tokens for Vault auth"
echo -e "  - Rotate auth key annually or if compromised\n"
