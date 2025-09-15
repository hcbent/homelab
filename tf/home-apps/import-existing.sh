#!/bin/bash

# Import existing home application VMs into new Terraform state

set -e

echo "🔄 Importing existing home application VMs..."

# Array of VM info: name:vmid:target_node (matching terraform.tfvars)
VMS=(
    "plex:101:pve1"
    "docker:102:pve1"
)

# Import each VM using Proxmox format: <node>/qemu/<vmid>
for i in "${!VMS[@]}"; do
    IFS=':' read -r vm_name vm_id target_node <<< "${VMS[$i]}"
    import_id="${target_node}/qemu/${vm_id}"

    echo "📦 Importing $vm_name (ID: $vm_id on $target_node) at index $i..."
    echo "   Using import ID: $import_id"

    terraform import "proxmox_vm_qemu.home_app_vms[$i]" "$import_id"

    if [ $? -eq 0 ]; then
        echo "✅ Successfully imported $vm_name"
    else
        echo "❌ Failed to import $vm_name"
        exit 1
    fi
done

echo ""
echo "🎉 Import complete! Running terraform plan to verify..."
terraform plan

echo ""
echo "✅ If the plan shows 'No changes' or only minor differences, the import was successful!"
echo "⚠️  If there are differences, you may need to adjust the configuration to match the existing VMs."