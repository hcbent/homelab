# Outputs for proxmox_vm module

output "vm_id" {
  description = "The ID of the created VM"
  value       = proxmox_vm_qemu.vm.id
}

output "vm_name" {
  description = "The name of the created VM"
  value       = proxmox_vm_qemu.vm.name
}

output "vm_ipconfig0" {
  description = "The ipconfig0 setting of the VM"
  value       = proxmox_vm_qemu.vm.ipconfig0
}

output "vm_default_ipv4" {
  description = "The default IPv4 address of the VM (if available)"
  value       = proxmox_vm_qemu.vm.default_ipv4_address
}

output "vm_target_node" {
  description = "The Proxmox node where the VM is deployed"
  value       = proxmox_vm_qemu.vm.target_node
}

output "vm_vmid" {
  description = "The VMID of the created VM"
  value       = proxmox_vm_qemu.vm.vmid
}
