# Monitoring cluster Terraform configuration

module "monitoring_vms" {
  source = "../modules/proxmox_vm"
  count = length(var.monitoring_vms)

  name           = var.monitoring_vms[count.index].name
  target_node    = var.monitoring_vms[count.index].target_node
  vmid           = var.monitoring_vms[count.index].vmid
  clone          = var.monitoring_vms[count.index].clone
  os_type        = var.monitoring_vms[count.index].os_type
  cores          = var.monitoring_vms[count.index].cores
  memory         = var.monitoring_vms[count.index].memory
  sockets        = var.monitoring_vms[count.index].sockets
  disk_size      = var.monitoring_vms[count.index].disk_size
  disk_storage   = var.monitoring_vms[count.index].disk_storage
  network_model  = var.monitoring_vms[count.index].network_model
  network_bridge = var.monitoring_vms[count.index].network_bridge
  ipconfig0      = var.monitoring_vms[count.index].ipconfig0
  tags           = var.monitoring_vms[count.index].tags

  # Cloud-init user configuration
  ciuser         = var.ciuser
  cipassword     = var.cipassword
  sshkeys        = var.sshkeys
}