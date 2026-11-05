# Milestone 0 provider spike: one disposable VM, VMID 500, host pve2.
# Checks: clone, add a 256 GB data disk, cloud-init network, resize the data disk, import with a zero-diff plan.

resource "proxmox_virtual_environment_vm" "spike" {
  name      = "ecm-spike-${var.vm_id}"
  node_name = var.node_name
  vm_id     = var.vm_id
  tags      = ["ecm-spike", "disposable"]
  pool_id   = var.pool_id

  # Cloning across hosts only works when the template's disk is on shared storage.
  clone {
    vm_id        = var.template_vm_id
    node_name    = var.template_node
    datastore_id = var.datastore_id
    full         = true
  }

  cpu {
    cores = 2
  }

  memory {
    dedicated = 2048
  }

  # The guest agent is left off here. With it on, apply waits for the agent to answer and hangs
  # if the template does not run it. Addresses are not needed for the five checks.
  agent {
    enabled = false
  }

  disk {
    datastore_id = var.datastore_id
    interface    = "scsi0"
    size         = 32
  }

  disk {
    datastore_id = var.datastore_id
    interface    = "scsi1"
    size         = var.data_disk_gb
    file_format  = "raw"
  }

  network_device {
    bridge = var.bridge
  }

  initialization {
    datastore_id = var.datastore_id
    ip_config {
      ipv4 {
        address = var.ipv4_address
        gateway = var.ipv4_gateway
      }
    }
  }

  lifecycle {
    prevent_destroy = false
  }
}
