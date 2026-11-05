# Adoption-style config for the already-existing VM 500: NO clone block, and the settings the VM inherited from
# the template are declared explicitly. Secret-bearing cloud-init user data is ignored, never stored.
resource "proxmox_virtual_environment_vm" "adopted" {
  name      = "ecm-spike-500"
  node_name = "pve2"
  vm_id     = 500
  tags      = ["disposable", "ecm-spike"]

  cpu {
    cores = 2
  }

  memory {
    dedicated = 2048
  }

  serial_device {
    device = "socket"
  }

  vga {
    type   = "serial0"
    memory = 16
  }

  disk {
    datastore_id = "tank"
    interface    = "scsi0"
    size         = 32
    file_format  = "qcow2"
  }

  disk {
    datastore_id = "tank"
    interface    = "scsi1"
    size         = 300
    file_format  = "raw"
  }

  network_device {
    bridge = "vmbr0"
  }

  initialization {
    datastore_id = "tank"
    interface    = "ide2"
    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }
  }

  lifecycle {
    # operating_system.type is not read back on import, so it always shows as a change if declared.
    ignore_changes = [initialization[0].user_account, operating_system]
  }
}
