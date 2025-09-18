variable "proxmox_host" {
    description = "The Proxmox VE endpoint."
    type        = string
}

variable "proxmox_username" {
    description = "The username for Proxmox VE."
    type        = string
}

variable "proxmox_password" {
    description = "The password for Proxmox VE."
    type        = string
    sensitive   = true
}

variable "proxmox_node" {
    description = "The Proxmox VE node to deploy the VM on."
    type        = string
}

variable "proxmox_vm_id" {
    description = "The ID of the existing Proxmox VM."
    type        = number
}

variable "k8s_version" {
    description = "The version of Kubernetes to install."
    type        = string
    default     = "1.21.0"
}

variable "k8s_cluster_name" {
    description = "The name of the Kubernetes cluster."
    type        = string
}

variable "k8s_node_name" {
    description = "The name of the Kubernetes node."
    type        = string
}

variable "ssh_user" {
    description = "The SSH user to connect to the VM."
    type        = string
}

variable "ssh_private_key" {
    description = "The private key for SSH authentication."
    type        = string
    sensitive   = true
}

variable "ssh_host" {
    description = "The hostname or IP address of the VM."
    type        = string
}

variable "tags" {
    description = "Tags for resources"
    type        = string
}
