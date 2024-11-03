# variables.tf 

variable "name" {
    description = "The name of the VM to create"
    type = string
    default = "linux-vm"
}

variable "target_node" {
    description = "The Proxmox node to deploy the VM on"
    type = string
    default = "pve"
}

variable "vmid" {
    description = "The ID of the VM to create"
    type = number
    default = 100
}

variable "clone" {
    description = "The ID of the VM to clone"
    type = number
    default = 8000
}

variable "cores" {
    description = "The number of CPU cores to allocate to the VM"
    type = number
    default = 2
}

variable "memory" {
    description = "The amount of memory to allocate to the VM (in MB)"
    type = number
    default = 2048
}

variable "sockets" {
    description = "The number of CPU sockets to allocate to the VM"
    type = number
    default = 1
}

variable "disk_size" {
    description = "The size of the VM's disk"
    type = string
    default = "10G"
}

variable "disk_storage" {
    description = "The storage type to use for the VM's disk"
    type = string
    default = "local-lvm"
}

variable "network_model" {
    description = "The network model to use for the VM"
    type = string
    default = "virtio"
}

variable "network_bridge" {
    description = "The bridge to connect the VM's network interface to"
    type = string
    default = "vmbr0"
}

variable "ipconfig0" {
    description = "The IP configuration for the VM's network interface"
    type = string
    default = "ip=dhcp"
}

variable "os_type" {
    description = "The type of operating system to install on the VM"
    type = string
    default = "linux"
}