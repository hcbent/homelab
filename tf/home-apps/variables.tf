# Home applications variables

variable "pm_api_url" {
  description = "The URL of the Proxmox API"
  type        = string
  default     = "https://pve1.lab.thewortmans.org:8006/api2/json"
}

variable "pm_tls_insecure" {
  description = "Whether to ignore TLS certificate errors"
  type        = bool
  default     = true
}

variable "pm_user" {
  description = "Proxmox username"
  type        = string
  sensitive   = true
}

variable "pm_password" {
  description = "Proxmox password"
  type        = string
  sensitive   = true
}


variable "ciuser" {
  description = "The cloud-init user to create"
  type        = string
  default     = "bret"
}

variable "cipassword" {
  description = "The password for the cloud-init user"
  type        = string
  sensitive   = true
}

variable "sshkeys" {
  description = "SSH public keys for the cloud-init user"
  type        = string
}

variable "home_app_vms" {
  description = "List of Home application VM configurations"
  type        = list(map(any))
}