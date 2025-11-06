# Outputs for nginx Load Balancer HA Cluster

# Individual node outputs
output "nginx_lb_node_hostnames" {
  description = "nginx load balancer node hostnames"
  value       = [for vm in module.nginx_lb_vms : vm.vm_name]
}

output "nginx_lb_node_ips" {
  description = "nginx load balancer node IP addresses"
  value       = [for vm in module.nginx_lb_vms : vm.vm_default_ipv4]
}

output "nginx_lb_node_vmids" {
  description = "nginx load balancer Proxmox VMIDs"
  value       = [for vm in module.nginx_lb_vms : vm.vm_vmid]
}

output "nginx_lb_target_nodes" {
  description = "Proxmox nodes hosting nginx load balancers"
  value       = [for vm in module.nginx_lb_vms : vm.vm_target_node]
}

# HA cluster outputs
output "cluster_vip" {
  description = "Virtual IP (VIP) address for the HA cluster"
  value       = var.cluster_vip
}

output "cluster_name" {
  description = "Name of the corosync/pacemaker HA cluster"
  value       = var.cluster_name
}

# Formatted output for Ansible inventory
output "ansible_inventory" {
  description = "Formatted output for Ansible inventory"
  value = {
    nginx_lb = {
      hosts = {
        for idx, vm in module.nginx_lb_vms :
        var.nginx_lb_vms[idx].name => {
          ansible_host = vm.vm_default_ipv4
          proxmox_node = var.nginx_lb_vms[idx].target_node
          vmid         = var.nginx_lb_vms[idx].vmid
        }
      }
      vars = {
        cluster_vip  = var.cluster_vip
        cluster_name = var.cluster_name
      }
    }
  }
}

# Deployment summary
output "deployment_summary" {
  description = "Summary of nginx load balancer HA cluster deployment"
  value = <<-EOT
  Nginx Load Balancer HA Cluster Deployed:

  Cluster Name: ${var.cluster_name}
  Virtual IP (VIP): ${var.cluster_vip}

  Node 1: ${var.nginx_lb_vms[0].name}
    - IP: ${var.nginx_lb_vms[0].ipconfig0}
    - Proxmox Host: ${var.nginx_lb_vms[0].target_node}
    - VMID: ${var.nginx_lb_vms[0].vmid}

  Node 2: ${var.nginx_lb_vms[1].name}
    - IP: ${var.nginx_lb_vms[1].ipconfig0}
    - Proxmox Host: ${var.nginx_lb_vms[1].target_node}
    - VMID: ${var.nginx_lb_vms[1].vmid}

  Next Steps:
  1. Verify SSH connectivity to both nodes
  2. Run Ansible inventory configuration (Task Group 3)
  3. Deploy nginx and corosync configuration (Task Group 4)
  EOT
}
