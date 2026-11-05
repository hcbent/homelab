variable "endpoint" {
  description = "Proxmox API endpoint of the target host."
  type        = string
  default     = "https://pve2.lab.thewortmans.org:8006/"
}

variable "insecure" {
  description = "Skip TLS verification. Off by default; turn on only if the host uses a self-signed certificate."
  type        = bool
  default     = false
}

variable "node_name" {
  description = "Proxmox host the spike VM is created on."
  type        = string
  default     = "pve2"
}

variable "vm_id" {
  description = "VMID for the spike VM. Must stay inside the approved 500-599 range."
  type        = number
  default     = 500
  validation {
    condition     = var.vm_id >= 500 && var.vm_id <= 599
    error_message = "vm_id must be between 500 and 599."
  }
}

variable "template_node" {
  description = "Host that holds the template."
  type        = string
  default     = "pve1"
}

variable "template_vm_id" {
  description = "Template to clone (ubuntu-25.04)."
  type        = number
  default     = 8000
}

variable "datastore_id" {
  description = "Datastore for the cloned disk, the data disk and the cloud-init drive."
  type        = string
  default     = "tank"
}

variable "data_disk_gb" {
  description = "Size of the second disk. Raise it and re-apply to test the resize step."
  type        = number
  default     = 256
}

variable "bridge" {
  description = "Bridge for the VM NIC."
  type        = string
  default     = "vmbr0"
}

variable "ipv4_address" {
  description = "Cloud-init IPv4 address: \"dhcp\" or a static address in CIDR form, for example 192.168.10.211/24."
  type        = string
  default     = "dhcp"
}

variable "ipv4_gateway" {
  description = "Cloud-init IPv4 gateway. Leave null with dhcp."
  type        = string
  default     = null
}

variable "pool_id" {
  description = "Resource pool the VM is created in. The API token holds its VM rights on this pool, so they survive destroy."
  type        = string
  default     = "ecm"
}
