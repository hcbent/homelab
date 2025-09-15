# Kubernetes cluster Terraform configuration

module "kubernetes_vms" {
  source = "../modules/proxmox_vm"
  count = length(var.kubernetes_vms)

  name           = var.kubernetes_vms[count.index].name
  target_node    = var.kubernetes_vms[count.index].target_node
  vmid           = var.kubernetes_vms[count.index].vmid
  clone          = var.kubernetes_vms[count.index].clone
  os_type        = var.kubernetes_vms[count.index].os_type
  cores          = var.kubernetes_vms[count.index].cores
  memory         = var.kubernetes_vms[count.index].memory
  sockets        = var.kubernetes_vms[count.index].sockets
  disk_size      = var.kubernetes_vms[count.index].disk_size
  disk_storage   = var.kubernetes_vms[count.index].disk_storage
  network_model  = var.kubernetes_vms[count.index].network_model
  network_bridge = var.kubernetes_vms[count.index].network_bridge
  ipconfig0      = var.kubernetes_vms[count.index].ipconfig0

  # Cloud-init user configuration
  ciuser         = var.ciuser
  cipassword     = var.cipassword
  sshkeys        = var.sshkeys
}