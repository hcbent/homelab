# Example Terraform configuration using Vault provider
# This demonstrates how to retrieve secrets from HashiCorp Vault

terraform {
  required_providers {
    vault = {
      source  = "hashicorp/vault"
      version = "~> 4.0"
    }
    proxmox = {
      source  = "telmate/proxmox"
      version = "~> 3.0"
    }
  }
}

# Configure Vault provider
provider "vault" {
  address = "https://vault.lab.thewortmans.org:8200"

  # Option 1: Use token from environment variable VAULT_TOKEN
  # token = var.vault_token

  # Option 2: Use userpass authentication
  # auth_login_userpass {
  #   username = "terraform"
  #   password = var.vault_password
  # }

  # Skip TLS verification for self-signed certificates (dev only)
  skip_tls_verify = true
}

# Read Proxmox credentials from Vault
data "vault_kv_secret_v2" "proxmox" {
  mount = "secret"
  name  = "homelab/proxmox/terraform"
}

# Read FreeNAS credentials from Vault
data "vault_kv_secret_v2" "freenas" {
  mount = "secret"
  name  = "homelab/freenas/credentials"
}

# Configure Proxmox provider using Vault secrets
provider "proxmox" {
  pm_api_url      = "https://pve1.lab.thewortmans.org:8006/api2/json"
  pm_user         = data.vault_kv_secret_v2.proxmox.data["username"]
  pm_password     = data.vault_kv_secret_v2.proxmox.data["password"]
  pm_tls_insecure = true
}

# Example: Use secrets in local-exec provisioner
resource "null_resource" "configure_freenas" {
  provisioner "local-exec" {
    command = <<-EOT
      curl -X POST https://192.168.2.24/api/v2.0/system/info \
        -H "Authorization: Bearer ${data.vault_kv_secret_v2.freenas.data["api_key"]}" \
        -k
    EOT
  }
}

# Example: Pass secrets as variables to module
module "example_vm" {
  source = "./modules/proxmox_vm"

  # ... other configuration ...

  # Use secret for cloud-init password
  cipassword = data.vault_kv_secret_v2.proxmox.data["ci_password"]
}

# Output secrets (marked as sensitive)
output "proxmox_user" {
  value     = data.vault_kv_secret_v2.proxmox.data["username"]
  sensitive = false  # Username is not sensitive
}

output "proxmox_password" {
  value     = data.vault_kv_secret_v2.proxmox.data["password"]
  sensitive = true   # Always mark secrets as sensitive
}
