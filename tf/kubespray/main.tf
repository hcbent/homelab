# Kubespray Kubernetes cluster Terraform configuration

# Local values using Vault secrets
locals {
  ciuser     = coalesce(var.ciuser, data.vault_kv_secret_v2.proxmox.data["ciuser"])
  cipassword = coalesce(var.cipassword, data.vault_kv_secret_v2.proxmox.data["cipassword"])
}

# Control plane VMs (km02, km03)
# Note: km01 is bare metal and not provisioned by Terraform
module "control_plane_vms" {
  source = "../modules/proxmox_vm"
  count  = length(var.control_plane_vms)

  name           = var.control_plane_vms[count.index].name
  target_node    = var.control_plane_vms[count.index].target_node
  vmid           = var.control_plane_vms[count.index].vmid
  clone          = var.control_plane_vms[count.index].clone
  os_type        = var.control_plane_vms[count.index].os_type
  cores          = var.control_plane_vms[count.index].cores
  memory         = var.control_plane_vms[count.index].memory
  sockets        = var.control_plane_vms[count.index].sockets
  disk_size      = var.control_plane_vms[count.index].disk_size
  disk_storage   = var.control_plane_vms[count.index].disk_storage
  network_model  = var.control_plane_vms[count.index].network_model
  network_bridge = var.control_plane_vms[count.index].network_bridge
  ipconfig0      = var.control_plane_vms[count.index].ipconfig0
  tags           = var.control_plane_vms[count.index].tags

  # Cloud-init user configuration from Vault
  ciuser     = local.ciuser
  cipassword = local.cipassword
  sshkeys    = var.sshkeys
}

# Worker VMs (kube01-kube03)
module "worker_vms" {
  source = "../modules/proxmox_vm"
  count  = length(var.worker_vms)

  name           = var.worker_vms[count.index].name
  target_node    = var.worker_vms[count.index].target_node
  vmid           = var.worker_vms[count.index].vmid
  clone          = var.worker_vms[count.index].clone
  os_type        = var.worker_vms[count.index].os_type
  cores          = var.worker_vms[count.index].cores
  memory         = var.worker_vms[count.index].memory
  sockets        = var.worker_vms[count.index].sockets
  disk_size      = var.worker_vms[count.index].disk_size
  disk_storage   = var.worker_vms[count.index].disk_storage
  network_model  = var.worker_vms[count.index].network_model
  network_bridge = var.worker_vms[count.index].network_bridge
  ipconfig0      = var.worker_vms[count.index].ipconfig0
  tags           = var.worker_vms[count.index].tags

  # Cloud-init user configuration from Vault
  ciuser     = local.ciuser
  cipassword = local.cipassword
  sshkeys    = var.sshkeys
}
