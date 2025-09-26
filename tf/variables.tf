# Description: Define the variables that will be used in the Terraform configuration
variable "pm_api_url" {
    description = "The URL of the Proxmox API"
    type = string
    default = "https://pve1.lab.thewortmans.org:8006/api2/json"
}

variable "proxmox_nodes" {
    description = "List of available Proxmox nodes"
    type = list(string)
    default = ["pve1.lab.thewortmans.org", "pve2.lab.thewortmans.org", "pve3.lab.thewortmans.org"]
}

variable "pm_tls_insecure" {
    description = "Whether to ignore TLS certificate errors"
    type = bool
    default = true
}

variable "vault_address" {
  description = "Vault server address"
  type        = string
  default     = "http://localhost:8200"
}

variable "vault_token" {
  description = "Vault authentication token"
  type        = string
  sensitive   = true
}

variable "pm_user" {
    description = "Proxmox username (retrieved from Vault)"
    type = string
    sensitive = true
    default = ""
}

variable "pm_password" {
    description = "Proxmox password (retrieved from Vault)"
    type = string
    sensitive = true
    default = ""
}

variable "vms" {
  description = "List of VM configurations"
  type        = list(map(string))
}
