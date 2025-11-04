terraform {
  required_providers {
    vault = {
      source  = "hashicorp/vault"
      version = "~> 5.0"
    }
  }
}

provider "vault" {
  address = var.vault_address
  token   = var.vault_token
}

data "vault_kv_secret_v2" "proxmox_credentials" {
  mount = "secret"
  name  = "proxmox"
}

data "vault_kv_secret_v2" "vm_credentials" {
  mount = "secret"
  name  = "vm-defaults"
}
