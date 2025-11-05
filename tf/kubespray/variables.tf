# Kubespray cluster Terraform variables

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

variable "control_plane_vms" {
  description = "List of control plane VM configurations (km02, km03)"
  type        = list(map(string))
}

variable "worker_vms" {
  description = "List of worker VM configurations (kube01-kube03)"
  type        = list(map(string))
}

variable "ciuser" {
  description = "The cloud-init user to create"
  type        = string
  default     = "bret"
}

variable "cipassword" {
  description = "The password for the cloud-init user (from Vault if not specified)"
  type        = string
  sensitive   = true
  default     = null
}

variable "sshkeys" {
  description = "SSH public keys for the cloud-init user"
  type        = string
}
