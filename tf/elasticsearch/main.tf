# Elasticsearch cluster Terraform configuration

module "elasticsearch_vms" {
  source = "../modules/proxmox_vm"
  count = length(var.elasticsearch_vms)

  name           = var.elasticsearch_vms[count.index].name
  target_node    = var.elasticsearch_vms[count.index].target_node
  vmid           = var.elasticsearch_vms[count.index].vmid
  clone          = var.elasticsearch_vms[count.index].clone
  os_type        = var.elasticsearch_vms[count.index].os_type
  cores          = var.elasticsearch_vms[count.index].cores
  memory         = var.elasticsearch_vms[count.index].memory
  sockets        = var.elasticsearch_vms[count.index].sockets
  disk_size      = var.elasticsearch_vms[count.index].disk_size
  disk_storage   = var.elasticsearch_vms[count.index].disk_storage
  network_model  = var.elasticsearch_vms[count.index].network_model
  network_bridge = var.elasticsearch_vms[count.index].network_bridge
  ipconfig0      = var.elasticsearch_vms[count.index].ipconfig0

  # Cloud-init user configuration
  ciuser         = var.ciuser
  cipassword     = var.cipassword
  sshkeys        = var.sshkeys
}