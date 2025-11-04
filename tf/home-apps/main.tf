# Home applications Terraform configuration

module "home_app_vms" {
  source = "../modules/proxmox_vm"
  count  = length(var.home_app_vms)

  name           = var.home_app_vms[count.index].name
  target_node    = var.home_app_vms[count.index].target_node
  vmid           = var.home_app_vms[count.index].vmid
  clone          = var.home_app_vms[count.index].clone
  os_type        = var.home_app_vms[count.index].os_type
  cores          = var.home_app_vms[count.index].cores
  memory         = var.home_app_vms[count.index].memory
  sockets        = var.home_app_vms[count.index].sockets
  disk_size      = var.home_app_vms[count.index].disk_size
  disk_storage   = var.home_app_vms[count.index].disk_storage
  network_model  = var.home_app_vms[count.index].network_model
  network_bridge = var.home_app_vms[count.index].network_bridge
  ipconfig0      = var.home_app_vms[count.index].ipconfig0
  tags           = var.home_app_vms[count.index].tags
  startup        = var.home_app_vms[count.index].startup
  hastate        = var.home_app_vms[count.index].hastate

  # Cloud-init user configuration
  ciuser     = var.ciuser
  cipassword = var.cipassword
  sshkeys    = var.sshkeys
}
