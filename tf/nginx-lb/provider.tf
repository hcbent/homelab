# Proxmox provider configuration

terraform {
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "~> 3.0"
    }
    vault = {
      source  = "hashicorp/vault"
      version = "~> 4.0"
    }
  }
}

provider "proxmox" {
  pm_user         = var.pm_user
  pm_password     = var.pm_password
  pm_api_url      = var.pm_api_url
  pm_tls_insecure = true
  pm_parallel     = 2
  pm_timeout      = 600
}
