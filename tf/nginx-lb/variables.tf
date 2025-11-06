# Variables for nginx Load Balancer HA Cluster

variable "nginx_lb_vms" {
  description = "List of nginx load balancer VM configurations for HA cluster"
  type = list(object({
    name           = string
    target_node    = string
    vmid           = number
    clone          = string
    os_type        = string
    cores          = number
    memory         = number
    sockets        = number
    disk_size      = string
    disk_storage   = string
    network_model  = string
    network_bridge = string
    ipconfig0      = string
    tags           = string
  }))

  validation {
    condition     = length(var.nginx_lb_vms) == 2
    error_message = "Exactly 2 nginx load balancer VMs must be defined for HA cluster."
  }

  validation {
    condition     = length(distinct([for vm in var.nginx_lb_vms : vm.target_node])) == 2
    error_message = "VMs must be deployed to different Proxmox hosts for anti-affinity."
  }
}

variable "cluster_vip" {
  description = "Virtual IP (VIP) address for the nginx load balancer HA cluster"
  type        = string
  default     = "192.168.10.250"

  validation {
    condition     = can(regex("^192\\.168\\.10\\.\\d{1,3}$", var.cluster_vip))
    error_message = "VIP must be in the 192.168.10.0/24 network range."
  }
}

variable "cluster_name" {
  description = "Name of the corosync/pacemaker HA cluster"
  type        = string
  default     = "nginx-lb-cluster"

  validation {
    condition     = length(var.cluster_name) > 0 && length(var.cluster_name) <= 32
    error_message = "Cluster name must be between 1 and 32 characters."
  }
}

variable "pm_api_url" {
  description = "The URL of the Proxmox API"
  type        = string
  default     = "https://pve1.lab.thewortmans.org:8006/api2/json"
}

variable "pm_user" {
  description = "Proxmox user for authentication"
  type        = string
  default     = "root@pam"
}

variable "pm_password" {
  description = "Proxmox password for authentication"
  type        = string
  sensitive   = true
}

variable "sshkeys" {
  description = "SSH public keys for cloud-init"
  type        = string
  sensitive   = true
}

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
