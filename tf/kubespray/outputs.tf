# Terraform outputs for kubespray inventory generation

# Bare metal control plane node (km01) - for reference, not provisioned
output "bare_metal_control_plane" {
  description = "Bare metal control plane node metadata"
  value = {
    hostname = "km01.lab.thewortmans.org"
    ip       = "192.168.10.234"
    role     = "control_plane"
    etcd     = true
  }
}

# Control plane VMs (km02, km03)
output "control_plane_vms" {
  description = "Control plane VM information"
  value = [
    for vm in module.control_plane_vms : {
      name     = vm.vm_name
      hostname = "${vm.vm_name}.lab.thewortmans.org"
      ip       = regex("ip=([0-9.]+)/", vm.vm_ipconfig0)[0]
      role     = "control_plane"
      etcd     = true
    }
  ]
}

# Worker VMs (kube01-kube03)
output "worker_vms" {
  description = "Worker VM information"
  value = [
    for vm in module.worker_vms : {
      name     = vm.vm_name
      hostname = "${vm.vm_name}.lab.thewortmans.org"
      ip       = regex("ip=([0-9.]+)/", vm.vm_ipconfig0)[0]
      role     = "worker"
      etcd     = false
    }
  ]
}

# All nodes for kubespray inventory
output "all_nodes" {
  description = "All cluster nodes for kubespray inventory generation"
  value = concat(
    [
      {
        name     = "km01"
        hostname = "km01.lab.thewortmans.org"
        ip       = "192.168.10.234"
        role     = "control_plane"
        etcd     = true
      }
    ],
    [
      for vm in module.control_plane_vms : {
        name     = vm.vm_name
        hostname = "${vm.vm_name}.lab.thewortmans.org"
        ip       = regex("ip=([0-9.]+)/", vm.vm_ipconfig0)[0]
        role     = "control_plane"
        etcd     = true
      }
    ],
    [
      for vm in module.worker_vms : {
        name     = vm.vm_name
        hostname = "${vm.vm_name}.lab.thewortmans.org"
        ip       = regex("ip=([0-9.]+)/", vm.vm_ipconfig0)[0]
        role     = "worker"
        etcd     = false
      }
    ]
  )
}

# Simple outputs for quick reference
output "control_plane_ips" {
  description = "IP addresses of all control plane nodes"
  value = concat(
    ["192.168.10.234"],  # km01 bare metal
    [for vm in module.control_plane_vms : regex("ip=([0-9.]+)/", vm.vm_ipconfig0)[0]]
  )
}

output "worker_ips" {
  description = "IP addresses of all worker nodes"
  value = [
    for vm in module.worker_vms : regex("ip=([0-9.]+)/", vm.vm_ipconfig0)[0]
  ]
}

output "etcd_nodes" {
  description = "Nodes running etcd (all control plane nodes)"
  value = concat(
    ["km01.lab.thewortmans.org"],
    [for vm in module.control_plane_vms : "${vm.vm_name}.lab.thewortmans.org"]
  )
}
