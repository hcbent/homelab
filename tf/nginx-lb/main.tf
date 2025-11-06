# nginx Load Balancer HA Cluster Terraform configuration
# Provisions two nginx VMs for high availability with corosync/pacemaker

# nginx Load Balancer VMs (list-based provisioning)
module "nginx_lb_vms" {
  source = "../modules/proxmox_vm"
  count  = length(var.nginx_lb_vms)

  name           = var.nginx_lb_vms[count.index].name
  target_node    = var.nginx_lb_vms[count.index].target_node
  vmid           = var.nginx_lb_vms[count.index].vmid
  clone          = var.nginx_lb_vms[count.index].clone
  os_type        = var.nginx_lb_vms[count.index].os_type
  cores          = var.nginx_lb_vms[count.index].cores
  memory         = var.nginx_lb_vms[count.index].memory
  sockets        = var.nginx_lb_vms[count.index].sockets
  disk_size      = var.nginx_lb_vms[count.index].disk_size
  disk_storage   = var.nginx_lb_vms[count.index].disk_storage
  network_model  = var.nginx_lb_vms[count.index].network_model
  network_bridge = var.nginx_lb_vms[count.index].network_bridge
  ipconfig0      = var.nginx_lb_vms[count.index].ipconfig0
  tags           = var.nginx_lb_vms[count.index].tags

  # Cloud-init user configuration
  ciuser     = var.ciuser
  cipassword = var.cipassword
  sshkeys    = var.sshkeys
}
