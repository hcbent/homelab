#!/bin/bash
# Setup script to store credentials in HashiCorp Vault
# Usage: ./setup-vault-secrets.sh

set -e

VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-}"

if [ -z "$VAULT_TOKEN" ]; then
    echo "Error: VAULT_TOKEN environment variable is required"
    echo "Usage: VAULT_TOKEN=your_token ./setup-vault-secrets.sh"
    exit 1
fi

echo "Setting up Vault secrets for Terraform..."
echo "Vault Address: $VAULT_ADDR"

# Enable KV v2 secret engine if not already enabled
vault auth -token="$VAULT_TOKEN" > /dev/null 2>&1 || {
    echo "Error: Failed to authenticate with Vault"
    exit 1
}

# Enable secrets engine
vault secrets enable -version=2 kv 2>/dev/null || echo "KV v2 engine already enabled"

# Store Proxmox credentials
echo "Storing Proxmox credentials..."
vault kv put secret/proxmox \
    username="root@pve" \
    password="Benm1les"

# Store VM default credentials
echo "Storing VM default credentials..."
vault kv put secret/vm-defaults \
    username="bret" \
    password="CHANGE_ME_VM_PASSWORD" \
    ssh_public_key="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC26I0e0v2ZSYBYUCMLRjlr2c1mekBs2ngR5CsVdGCqw2/G/GCwdTQ4MKWarvANz3MJ1QrUdjfeJuvI0a2eXR0OlCAxLqdg19nblgzgaZsvk/2K+hv3K3mDA882nAB9/RwyNxL0d9FUEES6iZ5A4NiX19luG7e4SWNIsuPOT25gGUPRRrCJPmnZWuO6vHNiTQT8MZlXVpnfntYoYBD5AW+bMobsUFpCc4g88pzX7lRnKrIAsvlTLjvLKlXUVE0ADBXgtk68i+FnejFspXvdnfQzCgfGgkX2Bxonp/S00DNnzsUfh+I/yHJOkxZEIB2uhwOZN+6bh1qfRsiS80f/zF1elvkDYDlROXE+U4W4HVSd33k2W9vsWlSVSlGHAFyBMuDurJFQZDNfHs+f3w2nT+Oxk4pJ7NtKWFT2XrCeZevpKiuDR6z/r6dh43S6j5QPwZxBdW3rRdcKIfxBLMDwCtlb/f6Q6vUQB0NwV/ULWlpELVl7QmTUBu36SWeVksUqFYfULXrZs6HNBsJKVZEzRxZW1OVguDfTFwejpqZk6oRM2/x4TqNKr3yVvNT3fF+pKsDH811eJSfFkLVTf4KYBFjESA4pAQBjvQmpxup1oxZxIoXH3AilnoOrIJjfjcnw52ETSaL0fJl2P11mROEnMbUA9w4lP9igLWcyYYInu5B6Sw== bret.wortman@damascusgrp.com"

echo "Vault secrets setup complete!"
echo ""
echo "You can now run Terraform with:"
echo "  export VAULT_TOKEN=your_token"
echo "  export VAULT_ADDR=$VAULT_ADDR"
echo "  terraform plan"
echo ""
echo "To verify secrets were stored:"
echo "  vault kv get secret/proxmox"
echo "  vault kv get secret/vm-defaults"