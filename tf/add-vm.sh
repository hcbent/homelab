#!/bin/bash

# Simple script to help add new VMs to your Proxmox cluster
# Usage: ./add-vm.sh <vm-name> [vmid] [cores] [memory] [disk-size]

set -e

VM_NAME="${1}"
VMID="${2:-$(date +%s | tail -c 4)}"  # Default to last 4 digits of timestamp
CORES="${3:-2}"
MEMORY="${4:-2048}"
DISK_SIZE="${5:-20G}"

if [ -z "$VM_NAME" ]; then
    echo "Usage: $0 <vm-name> [vmid] [cores] [memory] [disk-size]"
    echo "Example: $0 my-new-vm 301 4 4096 30G"
    exit 1
fi

echo "Adding VM configuration:"
echo "  Name: $VM_NAME"
echo "  VMID: $VMID"
echo "  Cores: $CORES"
echo "  Memory: ${MEMORY}MB"
echo "  Disk: $DISK_SIZE"
echo ""

# Create VM entry
VM_ENTRY=$(cat <<EOF
  {
    name           = "$VM_NAME"
    target_node    = "pve1.lab.thewortmans.org"
    vmid           = "$VMID"
    clone          = "8000"
    os_type        = "linux"
    cores          = "$CORES"
    memory         = "$MEMORY"
    sockets        = "1"
    disk_size      = "$DISK_SIZE"
    disk_storage   = "tank"
    network_model  = "virtio"
    network_bridge = "vmbr0"
    ipconfig0      = "ip=dhcp"
  }
EOF
)

echo "Add this entry to your homelab.tfvars file in the vms list:"
echo ""
echo "$VM_ENTRY"
echo ""
echo "Then run:"
echo "  terraform plan -var-file homelab.tfvars"
echo "  terraform apply -var-file homelab.tfvars"