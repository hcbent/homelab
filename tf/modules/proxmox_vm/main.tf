resource "proxmox_vm_qemu" "vm" {
  name        = var.name
  target_node = var.target_node
  vmid        = var.vmid
  clone       = var.clone
  full_clone  = var.full_clone
  os_type     = var.os_type
  agent       = 1
  bios        = "seabios"
  scsihw      = "virtio-scsi-pci"
  tags        = var.tags
  onboot      = var.onboot
  startup     = var.startup

  cpu {
    cores   = var.cores
    sockets = var.sockets
  }

  memory = var.memory

  network {
    id     = 0
    model  = var.network_model
    bridge = var.network_bridge
  }

  disks {
    ide {
      ide2 {
        cloudinit {
          storage = var.disk_storage
        }
      }
    }
    scsi {
      scsi0 {
        disk {
          size    = var.disk_size
          storage = var.disk_storage
        }
      }
    }
  }

  ipconfig0 = var.ipconfig0

  ciuser     = var.ciuser
  cipassword = var.cipassword != null ? var.cipassword : null
  sshkeys    = var.sshkeys

  # Additional cloud-init options
  searchdomain = "lab.thewortmans.org"
  nameserver   = "192.168.10.1"
  ciupgrade    = true

  # Console configuration - fixes Proxmox web console issues
  serial {
    id   = 0
    type = "socket"
  }


  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      # Core VM creation attributes that force replacement
      clone,
      full_clone,

      # Runtime and computed attributes
      boot,
      bootdisk,
      current_node,
      default_ipv4_address,
      default_ipv6_address,
      ssh_host,
      ssh_port,
      linked_vmid,
      unused_disk,
      reboot_required,

      # Network changes that might occur during runtime
      network,

      # Disk changes to prevent recreation
      disks,

      # Serial console changes
      serial,

      # Cloud-init and configuration that might differ
      ciupgrade,
      onboot,
      os_type,
      ipconfig0,
      cipassword,
      sshkeys,
      searchdomain,
      nameserver,

      # Provider-managed attributes
      additional_wait,
      agent_timeout,
      automatic_reboot,
      clone_wait,
      define_connection_info,
      description,
      skip_ipv4,
      skip_ipv6
    ]
  }
}

