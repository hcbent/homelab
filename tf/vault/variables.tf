# Vault VM Variables

variable "target_node" {
  description = "Proxmox node to deploy Vault VM"
  type        = string
  default     = "pve1"
}

variable "vmid" {
  description = "VM ID for Vault server"
  type        = number
  default     = 401
}

variable "clone" {
  description = "Template to clone from"
  type        = string
  default     = "ubuntu-25.04"
}

variable "cores" {
  description = "Number of CPU cores"
  type        = number
  default     = 2
}

variable "memory" {
  description = "Memory in MB"
  type        = number
  default     = 4096
}

variable "disk_size" {
  description = "Disk size"
  type        = string
  default     = "50G"
}

variable "disk_storage" {
  description = "Storage pool"
  type        = string
  default     = "tank"
}

variable "ipconfig0" {
  description = "IP configuration"
  type        = string
  default     = "ip=192.168.10.41/24,gw=192.168.10.1"
}

# Proxmox authentication
variable "pm_user" {
  description = "Proxmox user"
  type        = string
  sensitive   = true
}

variable "pm_password" {
  description = "Proxmox password"
  type        = string
  sensitive   = true
}

# Cloud-init configuration
variable "ciuser" {
  description = "Cloud-init user"
  type        = string
  default     = "bret"
}

variable "cipassword" {
  description = "Cloud-init password"
  type        = string
  sensitive   = true
}

variable "sshkeys" {
  description = "SSH public keys"
  type        = string
}
