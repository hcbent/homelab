# Home applications Terraform configuration

# Keep existing Plex VM with direct resource (don't change it)
resource "proxmox_vm_qemu" "plex" {
  name        = "plex"
  target_node = "pve1"
  vmid        = 101

  # Match existing configuration exactly to avoid changes
  agent                = 1
  automatic_reboot     = true
  boot                = "c"
  bootdisk            = "scsi0"
  ciuser              = "bret"
  define_connection_info = false
  full_clone          = false
  onboot              = true
  qemu_os             = "other"
  scsihw              = "virtio-scsi-pci"

  sshkeys = var.sshkeys

  # CPU configuration for plex (4 cores, 4 sockets)
  cpu {
    cores   = 4
    sockets = 4
    type    = "host"
  }

  memory = 32768

  # Network configuration
  network {
    id       = 0
    bridge   = "vmbr0"
    model    = "virtio"
    firewall = false
  }

  # Existing disk configuration
  dynamic "disk" {
    for_each = [1]
    content {
      slot    = "scsi0"
      size    = "105984M"
      storage = "tank"
      type    = "disk"
      backup  = true
      format  = "qcow2"
    }
  }

  # CloudInit disk
  dynamic "disk" {
    for_each = [1]
    content {
      slot    = "ide2"
      type    = "cloudinit"
      storage = "tank"
    }
  }

  ipconfig0 = "ip=192.168.10.146/24,gw=192.168.10.1"

  # Serial console
  serial {
    id   = 0
    type = "socket"
  }

  lifecycle {
    ignore_changes = [
      # Ignore most changes to keep Plex VM stable
      additional_wait,
      agent_timeout,
      automatic_reboot,
      balloon,
      ciupgrade,
      clone_wait,
      description,
      skip_ipv4,
      skip_ipv6,
      target_node,
      target_nodes,
      disk,
      disks
    ]
  }
}

# Use module for docker VM (this will be recreated with proper cloud-init)
module "docker_vm" {
  source = "../modules/proxmox_vm"

  name           = "docker"
  target_node    = "pve2"
  vmid           = 102
  clone          = "ubuntu-25.04"
  os_type        = "linux"
  cores          = 2
  memory         = 8192
  sockets        = 1
  disk_size      = "102400M"
  disk_storage   = "tank"
  network_model  = "virtio"
  network_bridge = "vmbr0"
  ipconfig0      = "ip=192.168.10.147/24,gw=192.168.10.1"

  # Cloud-init user configuration
  ciuser         = var.ciuser
  cipassword     = var.cipassword
  sshkeys        = var.sshkeys
}
