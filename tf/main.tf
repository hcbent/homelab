# main.terraform {
# Define the various VMs we need.

resource "proxmox_vm_qemu" "linux_vm" {
    name        = var.name
    target_node = var.target_node
    vmid        = var.vmid
    clone       = var.clone

    os_type = var.os_type
    cores   = var.cores
    memory  = var.memory
    sockets = var.sockets

    disk {
        size    = var.disk_size
        storage = var.disk_storage
    }

    network {
        model  = var.network_model
        bridge = var.network_bridge
    }

    ipconfig0 = var.ipconfig0
}