# Configure Vault provider
provider "vault" {
  address = "https://192.168.10.101:8200"

  # Use token from environment variable VAULT_TOKEN
  # Set with: export VAULT_TOKEN=$(vault login -token-only)

  skip_tls_verify = true  # For self-signed certificates
}

# Read Proxmox credentials from Vault
data "vault_kv_secret_v2" "proxmox" {
  mount = "secret"
  name  = "homelab/proxmox/terraform"
}

# Configure Proxmox provider using Vault secrets
provider "proxmox" {
  pm_api_url      = var.pm_api_url
  pm_user         = data.vault_kv_secret_v2.proxmox.data["username"]
  pm_password     = data.vault_kv_secret_v2.proxmox.data["password"]
  pm_tls_insecure = var.pm_tls_insecure
}
