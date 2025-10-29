#!/bin/bash
#
# Vault Configuration Script
# This script sets up the initial secret structure and policies for homelab
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

VAULT_ADDR="${VAULT_ADDR:-https://vault.lab.thewortmans.org:8200}"
VAULT_SKIP_VERIFY="${VAULT_SKIP_VERIFY:-true}"

export VAULT_ADDR
export VAULT_SKIP_VERIFY

echo -e "${BLUE}=== Vault Configuration for Homelab ===${NC}\n"

# Check if authenticated
if ! vault token lookup &>/dev/null; then
    echo -e "${RED}Error: Not authenticated to Vault${NC}"
    echo -e "Run: ${GREEN}vault login${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Authenticated to Vault${NC}\n"

# Enable KV secrets engine v2
echo -e "${YELLOW}Enabling KV secrets engine...${NC}"
vault secrets enable -path=secret kv-v2 2>/dev/null || echo "  KV secrets already enabled"

# Create secret paths
echo -e "\n${YELLOW}Creating secret path structure...${NC}"

# Proxmox secrets
echo -e "  Creating ${BLUE}secret/homelab/proxmox${NC}"
vault kv put secret/homelab/proxmox/terraform \
    username="terraform@pve" \
    password="CHANGE_ME" \
    api_token="" || true

# TrueNAS/FreeNAS secrets
echo -e "  Creating ${BLUE}secret/homelab/freenas${NC}"
vault kv put secret/homelab/freenas/credentials \
    api_key="CHANGE_ME" \
    root_password="CHANGE_ME" || true

vault kv put secret/homelab/freenas/ssh \
    private_key="CHANGE_ME" \
    public_key="" || true

# Elasticsearch secrets
echo -e "  Creating ${BLUE}secret/homelab/elasticsearch${NC}"
vault kv put secret/homelab/elasticsearch/passwords \
    elastic_password="CHANGE_ME" \
    kibana_password="CHANGE_ME" \
    monitoring_password="CHANGE_ME" || true

# Media app secrets
echo -e "  Creating ${BLUE}secret/homelab/apps${NC}"
vault kv put secret/homelab/apps/plex \
    claim_token="CHANGE_ME" || true

vault kv put secret/homelab/apps/radarr \
    api_key="CHANGE_ME" || true

vault kv put secret/homelab/apps/sonarr \
    api_key="CHANGE_ME" || true

vault kv put secret/homelab/apps/lidarr \
    api_key="CHANGE_ME" || true

vault kv put secret/homelab/apps/qbittorrent \
    password="CHANGE_ME" || true

# Home Assistant secrets
echo -e "  Creating ${BLUE}secret/homelab/home-assistant${NC}"
vault kv put secret/homelab/home-assistant/config \
    api_token="CHANGE_ME" \
    latitude="" \
    longitude="" || true

# Database secrets
echo -e "  Creating ${BLUE}secret/homelab/databases${NC}"
vault kv put secret/homelab/databases/mysql \
    root_password="CHANGE_ME" || true

vault kv put secret/homelab/databases/postgresql \
    postgres_password="CHANGE_ME" || true

# Create policies
echo -e "\n${YELLOW}Creating Vault policies...${NC}"

# Terraform policy
cat > /tmp/terraform-policy.hcl <<EOF
# Policy for Terraform to read infrastructure secrets
path "secret/data/homelab/proxmox/*" {
  capabilities = ["read", "list"]
}

path "secret/data/homelab/freenas/*" {
  capabilities = ["read", "list"]
}
EOF
vault policy write terraform /tmp/terraform-policy.hcl

# Ansible policy
cat > /tmp/ansible-policy.hcl <<EOF
# Policy for Ansible to read all homelab secrets
path "secret/data/homelab/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/homelab/*" {
  capabilities = ["read", "list"]
}
EOF
vault policy write ansible /tmp/ansible-policy.hcl

# Applications policy
cat > /tmp/apps-policy.hcl <<EOF
# Policy for applications to read their specific secrets
path "secret/data/homelab/apps/*" {
  capabilities = ["read", "list"]
}

path "secret/data/homelab/databases/*" {
  capabilities = ["read", "list"]
}
EOF
vault policy write apps /tmp/apps-policy.hcl

# Admin policy
cat > /tmp/admin-policy.hcl <<EOF
# Administrative policy for managing all secrets
path "secret/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "sys/policies/acl/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "auth/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}
EOF
vault policy write admin /tmp/admin-policy.hcl

# Clean up temporary policy files
rm /tmp/*-policy.hcl

# Enable userpass auth for automation
echo -e "\n${YELLOW}Enabling userpass authentication...${NC}"
vault auth enable userpass 2>/dev/null || echo "  Userpass auth already enabled"

# Create automation users
echo -e "\n${YELLOW}Creating automation users...${NC}"
vault write auth/userpass/users/terraform \
    password="CHANGE_ME_TERRAFORM_PASSWORD" \
    policies="terraform"

vault write auth/userpass/users/ansible \
    password="CHANGE_ME_ANSIBLE_PASSWORD" \
    policies="ansible"

echo -e "\n${GREEN}✓ Vault configuration complete!${NC}\n"

echo -e "${BLUE}Summary of created secrets:${NC}"
echo -e "  ${GREEN}secret/homelab/proxmox/*${NC} - Proxmox credentials"
echo -e "  ${GREEN}secret/homelab/freenas/*${NC} - TrueNAS/FreeNAS credentials"
echo -e "  ${GREEN}secret/homelab/elasticsearch/*${NC} - Elasticsearch passwords"
echo -e "  ${GREEN}secret/homelab/apps/*${NC} - Application API keys"
echo -e "  ${GREEN}secret/homelab/home-assistant/*${NC} - Home Assistant config"
echo -e "  ${GREEN}secret/homelab/databases/*${NC} - Database passwords"

echo -e "\n${BLUE}Created policies:${NC}"
echo -e "  ${GREEN}terraform${NC} - For Terraform automation"
echo -e "  ${GREEN}ansible${NC} - For Ansible automation"
echo -e "  ${GREEN}apps${NC} - For applications"
echo -e "  ${GREEN}admin${NC} - For administrative tasks"

echo -e "\n${YELLOW}IMPORTANT: Update all 'CHANGE_ME' placeholders with actual values!${NC}"
echo -e "Example: ${GREEN}vault kv put secret/homelab/freenas/credentials api_key=YOUR_ACTUAL_KEY${NC}"

echo -e "\n${YELLOW}Next steps:${NC}"
echo -e "1. Update secrets with actual values"
echo -e "2. Run: ${GREEN}./04-rotate-credentials.sh${NC} to rotate exposed credentials"
echo -e "3. Configure Terraform/Ansible to use Vault"
