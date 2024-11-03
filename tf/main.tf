# main.terraform {
# Define the various VMs we need.

# Iterate over each VM in the list and create a module instance
module "proxmox_vms" {
  source = "./modules/proxmox_vm"
  for_each = var.vms

  name           = each.value.name
  target_node    = each.value.target_node
  vmid           = each.value.vmid
  clone          = each.value.clone
  os_type        = each.value.os_type
  cores          = each.value.cores
  memory         = each.value.memory
  sockets        = each.value.sockets
  disk_size      = each.value.disk_size
  disk_storage   = each.value.disk_storage
  network_model  = each.value.network_model
  network_bridge = each.value.network_bridge
  ipconfig0      = each.value.ipconfig0
}
