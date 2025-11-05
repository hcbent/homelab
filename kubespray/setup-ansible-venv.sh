#!/bin/bash
# Setup Python virtual environment with compatible Ansible version for kubespray
#
# Kubespray requires Ansible >= 2.17.3 and < 2.18.0
# This script creates a venv with the correct version

set -e

VENV_DIR="$HOME/git/kubespray/venv"

echo "Creating Python virtual environment at $VENV_DIR..."
python3 -m venv "$VENV_DIR"

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

echo "Installing kubespray requirements..."
pip install --upgrade pip
pip install -r "$HOME/git/kubespray/requirements.txt"

echo ""
echo "✓ Virtual environment created successfully!"
echo ""
echo "Ansible version installed:"
ansible --version | head -1
echo ""
echo "To use this environment:"
echo "  source ~/git/kubespray/venv/bin/activate"
echo ""
echo "Then run kubespray:"
echo "  cd ~/git/kubespray"
echo "  ansible-playbook -i /Users/bret/git/homelab/kubespray/inventory/homelab/hosts.ini cluster.yml"
echo ""
echo "To deactivate when done:"
echo "  deactivate"
