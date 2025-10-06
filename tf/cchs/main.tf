# CCHS VM Terraform configuration

module "cchs_vms" {
  source = "../modules/proxmox_vm"
  count = length(var.vms)

  name           = var.vms[count.index].name
  target_node    = var.vms[count.index].target_node
  vmid           = var.vms[count.index].vmid
  clone          = var.vms[count.index].clone
  os_type        = var.vms[count.index].os_type
  cores          = var.vms[count.index].cores
  memory         = var.vms[count.index].memory
  sockets        = var.vms[count.index].sockets
  disk_size      = var.vms[count.index].disk_size
  disk_storage   = var.vms[count.index].disk_storage
  network_model  = var.vms[count.index].network_model
  network_bridge = var.vms[count.index].network_bridge
  ipconfig0      = var.vms[count.index].ipconfig0

  # Cloud-init user configuration
  ciuser         = var.ciuser
  cipassword     = var.cipassword
  sshkeys        = var.sshkeys
}
