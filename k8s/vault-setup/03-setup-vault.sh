#!/bin/bash
#
# Vault Setup Script for Homelab Kubernetes Integration
# This script configures Vault to work with Kubernetes and sets up authentication
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Vault Kubernetes Integration Setup ===${NC}\n"

# Check if running in the right context
CURRENT_CONTEXT=$(kubectl config current-context)
echo -e "${YELLOW}Current kubectl context: ${CURRENT_CONTEXT}${NC}"
read -p "Is this the correct cluster? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${RED}Aborted. Please switch to the correct context.${NC}"
    exit 1
fi

# Set Vault address
VAULT_ADDR=${VAULT_ADDR:-"http://vault.vault.svc.cluster.local:8200"}
VAULT_POD=$(kubectl get pods -n vault -l app.kubernetes.io/name=vault -o jsonpath='{.items[0].metadata.name}')

echo -e "\n${GREEN}Step 1: Checking Vault status${NC}"
kubectl exec -n vault ${VAULT_POD} -- vault status || true

echo -e "\n${YELLOW}You will need to authenticate to Vault. Please have your root token ready.${NC}"
read -p "Press enter to continue..."

# Function to execute vault commands in the pod
vault_exec() {
    kubectl exec -n vault ${VAULT_POD} -- vault "$@"
}

echo -e "\n${GREEN}Step 2: Enabling Kubernetes auth method${NC}"
vault_exec auth enable kubernetes 2>/dev/null || echo "Kubernetes auth already enabled"

echo -e "\n${GREEN}Step 3: Configuring Kubernetes auth${NC}"
# Get the Kubernetes host
K8S_HOST="https://kubernetes.default.svc:443"

# Get the service account JWT
SA_JWT_TOKEN=$(kubectl get secret -n vault vault-token-<ID> -o jsonpath='{.data.token}' | base64 -d 2>/dev/null || echo "")

if [ -z "$SA_JWT_TOKEN" ]; then
    echo -e "${YELLOW}Creating service account token...${NC}"
    kubectl apply -f 01-vault-auth.yaml
    # Wait for token to be created
    sleep 2
    SA_JWT_TOKEN=$(kubectl create token vault-auth -n vault)
fi

# Get the CA cert
SA_CA_CRT=$(kubectl get cm kube-root-ca.crt -n vault -o jsonpath='{.data.ca\.crt}' | base64 -w 0)

# Configure Kubernetes auth
cat <<EOF | vault_exec write auth/kubernetes/config -
{
  "kubernetes_host": "${K8S_HOST}",
  "kubernetes_ca_cert": "$(echo ${SA_CA_CRT} | base64 -d)",
  "disable_local_ca_jwt": false
}
EOF

echo -e "\n${GREEN}Step 4: Creating Vault policies${NC}"
vault_exec policy write democratic-csi - <<EOF
path "secret/data/homelab/freenas/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/homelab/freenas/*" {
  capabilities = ["read", "list"]
}
EOF

vault_exec policy write elasticsearch - <<EOF
path "secret/data/homelab/elasticsearch/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/homelab/elasticsearch/*" {
  capabilities = ["read", "list"]
}
EOF

vault_exec policy write homelab-apps - <<EOF
path "secret/data/homelab/apps/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/homelab/apps/*" {
  capabilities = ["read", "list"]
}
EOF

echo -e "\n${GREEN}Step 5: Creating Kubernetes auth roles${NC}"

# Role for democratic-csi
vault_exec write auth/kubernetes/role/democratic-csi \
    bound_service_account_names=democratic-csi-vault \
    bound_service_account_namespaces=democratic-csi \
    policies=democratic-csi \
    ttl=24h

# Role for elasticsearch
vault_exec write auth/kubernetes/role/elasticsearch \
    bound_service_account_names=elasticsearch \
    bound_service_account_namespaces=elastic-stack \
    policies=elasticsearch \
    ttl=24h

# Role for apps
vault_exec write auth/kubernetes/role/homelab-apps \
    bound_service_account_names=vault-secrets-user \
    bound_service_account_namespaces=default,media,home-automation \
    policies=homelab-apps \
    ttl=24h

echo -e "\n${GREEN}Step 6: Enabling KV secrets engine${NC}"
vault_exec secrets enable -path=secret kv-v2 2>/dev/null || echo "KV secrets engine already enabled"

echo -e "\n${GREEN}Step 7: Creating secret structure${NC}"
# Create placeholder secrets (you'll need to populate these with actual values)
vault_exec kv put secret/homelab/freenas/api-key value="REPLACE_WITH_ACTUAL_API_KEY"
vault_exec kv put secret/homelab/freenas/password value="REPLACE_WITH_ACTUAL_PASSWORD"
vault_exec kv put secret/homelab/freenas/ssh-private-key value="REPLACE_WITH_ACTUAL_SSH_KEY"

echo -e "\n${GREEN}=== Setup Complete ===${NC}\n"
echo -e "${YELLOW}Next steps:${NC}"
echo -e "1. Update secrets in Vault:"
echo -e "   ${GREEN}kubectl exec -n vault ${VAULT_POD} -- vault kv put secret/homelab/freenas/api-key value=YOUR_API_KEY${NC}"
echo -e "2. Deploy democratic-csi with Vault integration"
echo -e "3. Test secret retrieval"
echo -e "\n${YELLOW}To manually retrieve secrets:${NC}"
echo -e "   ${GREEN}kubectl exec -n vault ${VAULT_POD} -- vault kv get secret/homelab/freenas/api-key${NC}"
