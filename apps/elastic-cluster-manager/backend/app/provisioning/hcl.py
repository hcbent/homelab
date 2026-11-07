"""The static Terraform configuration ECM renders. No user data is ever interpolated into this text.

Everything cluster-specific travels in cluster.auto.tfvars.json (see render.py), so a node name or a setting
can never become HCL. The only generated HCL is the backend schema name, which is validated first.

Lessons from the Milestone 0 spike (spike/FINDINGS.md) that shape this module:
  * the clone block makes an existing VM un-importable, so this module is for CREATE only; adoption gets its
    own generated configuration
  * the guest agent is off by default, because apply waits for the agent and hangs if the template lacks it
  * tags are sorted, because Proxmox returns them sorted and an unsorted list shows as a change
  * cloning to another host works only when the template disk is on shared storage
  * the pool, not a per-VMID rule, carries the API token's rights, so VMs can be destroyed and recreated
"""

PROVIDER_VERSION = "0.119.0"  # exact pin, per DECISIONS ("exact-version pinned")

VERSIONS_TF = f'''terraform {{
  required_version = ">= 1.6"
  required_providers {{
    proxmox = {{
      source  = "bpg/proxmox"
      version = "{PROVIDER_VERSION}"
    }}
  }}
}}

# The API token comes from the PROXMOX_VE_API_TOKEN environment variable at run time.
# It is never written to a file.
provider "proxmox" {{
  endpoint = var.proxmox_endpoint
  insecure = var.proxmox_insecure
}}
'''

# {schema} is the only substitution in any HCL file, and render.py validates it before use.
BACKEND_PG_TF = '''# Terraform state lives in Postgres. The connection string comes from the PG_CONN_STR environment variable.
terraform {{
  backend "pg" {{
    schema_name = "{schema}"
  }}
}}
'''

VARIABLES_TF = '''variable "proxmox_endpoint" {
  description = "Proxmox API endpoint."
  type        = string
}

variable "proxmox_insecure" {
  description = "Skip TLS verification. Off unless the connection explicitly opted in."
  type        = bool
  default     = false
}

variable "cluster_name" {
  type = string
}

variable "pool_id" {
  description = "Resource pool the VMs are created in. The API token holds its rights on this pool."
  type        = string
}

variable "template" {
  description = "The VM template to clone."
  type = object({
    node_name = string
    vm_id     = number
  })
}

variable "datastore_id" {
  type = string
}

variable "bridge" {
  type = string
}

variable "vlan_id" {
  type    = number
  default = null
}

variable "dns_servers" {
  type = list(string)
}

variable "search_domain" {
  type    = string
  default = null
}

variable "agent_enabled" {
  type    = bool
  default = false
}

variable "cpu_type" {
  description = "Proxmox CPU type. host exposes the real CPU features, which Elasticsearch machine learning needs."
  type        = string
  default     = "host"
}

variable "nodes" {
  description = "One entry per Elasticsearch node, keyed by node name."
  type = map(object({
    node_name    = string
    vm_id        = number
    cores        = number
    memory_mb    = number
    os_disk_gb   = number
    data_disk_gb = optional(number)
    address      = string
    gateway      = string
  }))
}
'''

MAIN_TF = '''module "node" {
  source   = "./modules/es_node"
  for_each = var.nodes

  name          = each.key
  cluster_name  = var.cluster_name
  node_name     = each.value.node_name
  vm_id         = each.value.vm_id
  pool_id       = var.pool_id
  template      = var.template
  datastore_id  = var.datastore_id
  cores         = each.value.cores
  memory_mb     = each.value.memory_mb
  os_disk_gb    = each.value.os_disk_gb
  data_disk_gb  = each.value.data_disk_gb
  bridge        = var.bridge
  vlan_id       = var.vlan_id
  address       = each.value.address
  gateway       = each.value.gateway
  dns_servers   = var.dns_servers
  search_domain = var.search_domain
  agent_enabled = var.agent_enabled
  cpu_type      = var.cpu_type
}
'''

OUTPUTS_TF = '''output "vms" {
  description = "What was created: IDs, hosts and addresses only."
  value = {
    for name, m in module.node : name => {
      vm_id     = m.vm_id
      node_name = m.node_name
      address   = m.address
    }
  }
}
'''

MODULE_VARIABLES_TF = '''variable "name" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "node_name" {
  type = string
}

variable "vm_id" {
  type = number
}

variable "pool_id" {
  type = string
}

variable "template" {
  type = object({
    node_name = string
    vm_id     = number
  })
}

variable "datastore_id" {
  type = string
}

variable "cores" {
  type = number
}

variable "memory_mb" {
  type = number
}

variable "os_disk_gb" {
  type = number
}

variable "data_disk_gb" {
  type    = number
  default = null
}

variable "bridge" {
  type = string
}

variable "vlan_id" {
  type    = number
  default = null
}

variable "address" {
  type = string
}

variable "gateway" {
  type = string
}

variable "dns_servers" {
  type = list(string)
}

variable "search_domain" {
  type    = string
  default = null
}

variable "agent_enabled" {
  type    = bool
  default = false
}

variable "cpu_type" {
  type    = string
  default = "host"
}
'''

MODULE_MAIN_TF = '''resource "proxmox_virtual_environment_vm" "this" {
  name      = var.name
  node_name = var.node_name
  vm_id     = var.vm_id
  pool_id   = var.pool_id
  tags      = sort(["ecm", var.cluster_name])
  on_boot   = true
  started   = true
  # Never restart a VM as a side effect of an update. A change that needs a restart (a new CPU or memory size) is
  # applied by ECM's own rolling restart, one node at a time, so Terraform must not take two nodes down at once.
  # If the provider cannot apply a change without taking the VM offline it fails instead (docs, v0.119.0).
  reboot_after_update = false

  clone {
    vm_id        = var.template.vm_id
    node_name    = var.template.node_name
    datastore_id = var.datastore_id
    full         = true
  }

  cpu {
    cores = var.cores
    type  = var.cpu_type
  }

  memory {
    dedicated = var.memory_mb
  }

  agent {
    enabled = var.agent_enabled
  }

  disk {
    datastore_id = var.datastore_id
    interface    = "scsi0"
    size         = var.os_disk_gb
  }

  dynamic "disk" {
    for_each = var.data_disk_gb == null ? [] : [var.data_disk_gb]
    content {
      datastore_id = var.datastore_id
      interface    = "scsi1"
      size         = disk.value
      file_format  = "raw"
    }
  }

  network_device {
    bridge  = var.bridge
    vlan_id = var.vlan_id
  }

  initialization {
    datastore_id = var.datastore_id
    ip_config {
      ipv4 {
        address = var.address
        gateway = var.gateway
      }
    }
    dns {
      servers = var.dns_servers
      domain  = var.search_domain
    }
  }
}
'''

MODULE_OUTPUTS_TF = '''output "vm_id" {
  value = proxmox_virtual_environment_vm.this.vm_id
}

output "node_name" {
  value = proxmox_virtual_environment_vm.this.node_name
}

output "address" {
  value = var.address
}
'''

# A child module must name its provider's source itself. Without this, Terraform assumes hashicorp/proxmox for
# the proxmox_virtual_environment_vm resource and init fails. The version constraint is inherited from the root.
MODULE_VERSIONS_TF = '''terraform {
  required_providers {
    proxmox = {
      source = "bpg/proxmox"
    }
  }
}
'''
