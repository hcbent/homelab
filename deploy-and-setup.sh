#!/bin/bash

# Integrated deployment script - Terraform + Ansible
# Usage: ./deploy-and-setup.sh [elasticsearch|kubernetes|all]

set -e

CLUSTER_TYPE="${1:-all}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="$SCRIPT_DIR/tf"
ANSIBLE_DIR="$SCRIPT_DIR/ansible"

echo "🚀 Starting deployment for: $CLUSTER_TYPE"

# Deploy infrastructure with Terraform
case $CLUSTER_TYPE in
    "elasticsearch")
        echo "📦 Deploying Elasticsearch cluster..."
        cd "$TF_DIR/elasticsearch"
        terraform init
        terraform plan
        read -p "Apply Terraform changes? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            terraform apply
        else
            echo "❌ Deployment cancelled"
            exit 0
        fi
        ;;
    "kubernetes")
        echo "📦 Deploying Kubernetes cluster..."
        cd "$TF_DIR/kubernetes"
        terraform init
        terraform plan
        read -p "Apply Terraform changes? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            terraform apply
        else
            echo "❌ Deployment cancelled"
            exit 0
        fi
        ;;
    "all")
        echo "📦 Deploying both clusters..."

        # Deploy Elasticsearch
        cd "$TF_DIR/elasticsearch"
        terraform init
        terraform plan
        read -p "Apply Elasticsearch changes? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            terraform apply
        else
            echo "❌ Elasticsearch deployment cancelled"
        fi

        # Deploy Kubernetes
        cd "$TF_DIR/kubernetes"
        terraform init
        terraform plan
        read -p "Apply Kubernetes changes? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            terraform apply
        else
            echo "❌ Kubernetes deployment cancelled"
        fi
        ;;
    *)
        echo "❌ Invalid cluster type. Use: elasticsearch, kubernetes, or all"
        exit 1
        ;;
esac

echo "✅ Terraform deployment complete!"
echo ""
echo "⏳ Waiting for VMs to be ready..."
sleep 30

cd "$ANSIBLE_DIR"

# Setup VMs with Ansible
echo "🔧 Setting up VMs with Ansible..."
echo "📝 Please update the inventory_new_vms file with the actual IP addresses of your new VMs"
echo "   You can get the IPs from Proxmox web UI or by running:"
echo "   terraform show | grep -E 'default_ipv4_address|name'"
echo ""
read -p "Press Enter when inventory is updated..."

echo "🔧 Installing QEMU Guest Agent and basic setup..."
ansible-playbook -i inventory_new_vms setup_new_vms.yml

echo ""
echo "🎉 Deployment and setup complete!"
echo ""
echo "📋 Next steps:"
case $CLUSTER_TYPE in
    "elasticsearch")
        echo "   - Configure Elasticsearch cluster"
        echo "   - Set up Kibana"
        echo "   - Configure Fleet server"
        ;;
    "kubernetes")
        echo "   - Run Kubernetes setup playbooks:"
        echo "     ansible-playbook -i inventory 01_setup_k8s.yml"
        echo "     ansible-playbook -i inventory 02_setup_first_cp_node.yml"
        echo "     ansible-playbook -i inventory 02_setup_other_cp_nodes.yml"
        echo "     ansible-playbook -i inventory 02_setup_worker.yml"
        ;;
    "all")
        echo "   - Run all your existing Ansible playbooks"
        echo "   - Configure services as needed"
        ;;
esac