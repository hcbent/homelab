# Elasticsearch cluster variables

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

# Note: pm_user and pm_password are now retrieved from Vault
# No longer defined as variables - see provider.tf

variable "elasticsearch_vms" {
  description = "List of Elasticsearch VM configurations"
  type        = list(map(string))
}

# Note: ciuser and cipassword are now retrieved from Vault
# These variables are kept for backward compatibility but default values removed

variable "ciuser" {
  description = "The cloud-init user to create"
  type        = string
  default     = ""  # Retrieved from Vault
}

variable "cipassword" {
  description = "The password for the cloud-init user"
  type        = string
  sensitive   = true
  default     = ""  # Retrieved from Vault
}

variable "sshkeys" {
  description = "SSH public keys for the cloud-init user"
  type        = string
}
