# Description: Define the variables that will be used in the Terraform configuration
variable "pm_api_url" {
    description = "The URL of the Proxmox API"
    type = string
    default = "https://192.168.1.20:8006/api2/json"
}

variable "pm_tls_insecure" {
    description = "Whether to ignore TLS certificate errors"
    type = bool
    default = true
}

variable "vms" {
  description = "List of VM configurations"
  type        = list(map(string))
}
