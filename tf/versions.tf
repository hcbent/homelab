terraform {
  required_providers {
    proxmox = {
      source = "telmate/proxmox"
      version = "3.0.2-rc05"
    }
    # vault = {
    #   source = "hashicorp/vault"
    #   version = "~> 5.0"
    # }
  }
}
