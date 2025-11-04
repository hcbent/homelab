# Vault VM Terraform configuration

module "vault_vm" {
  source = "../modules/proxmox_vm"

  name           = "vault"
  target_node    = var.target_node
  vmid           = var.vmid
  clone          = var.clone
  os_type        = "linux"
  cores          = var.cores
  memory         = var.memory
  sockets        = 1
  disk_size      = var.disk_size
  disk_storage   = var.disk_storage
  network_model  = "virtio"
  network_bridge = "vmbr0"
  ipconfig0      = var.ipconfig0
  tags           = "vault,security,infrastructure"

  # Cloud-init user configuration
  ciuser     = var.ciuser
  cipassword = var.cipassword
  sshkeys    = var.sshkeys
}

output "vault_vm_ip" {
  description = "IP address of the Vault VM"
  value       = var.ipconfig0
}

output "vault_vm_id" {
  description = "VM ID of the Vault server"
  value       = var.vmid
}
