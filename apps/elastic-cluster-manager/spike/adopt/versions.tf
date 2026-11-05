terraform {
  required_version = ">= 1.6"
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.119"
    }
  }
}

# The API token comes from PROXMOX_VE_API_TOKEN ("user@realm!tokenid=secret"). It is never written to a file here.
provider "proxmox" {
  endpoint = var.endpoint
  insecure = var.insecure
}
