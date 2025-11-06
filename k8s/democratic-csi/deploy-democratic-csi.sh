#!/bin/bash
# Script to deploy Democratic CSI with credentials from Vault
# This keeps secrets out of Git

set -e

export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_SKIP_VERIFY="true"

echo "Retrieving TrueNAS credentials from Vault..."
TRUENAS_HOST=$(vault kv get -field=host secret/homelab/freenas/credentials)
TRUENAS_API_KEY=$(vault kv get -field=api_key secret/homelab/freenas/credentials)
TRUENAS_USERNAME=$(vault kv get -field=username secret/homelab/freenas/credentials)
TRUENAS_SSH_KEY=$(vault kv get -field=ssh_private_key secret/homelab/freenas/credentials)

echo "Deploying Democratic CSI iSCSI driver..."
helm upgrade --install freenas-iscsi democratic-csi/democratic-csi \
  --namespace democratic-csi \
  --create-namespace \
  --values /Users/bret/git/homelab/k8s/democratic-csi/values-iscsi.yaml \
  --set driver.config.httpConnection.host="$TRUENAS_HOST" \
  --set driver.config.httpConnection.apiKey="$TRUENAS_API_KEY" \
  --set driver.config.sshConnection.host="$TRUENAS_HOST" \
  --set driver.config.sshConnection.username="$TRUENAS_USERNAME" \
  --set driver.config.sshConnection.privateKey="$TRUENAS_SSH_KEY" \
  --wait \
  --timeout 5m

echo "Deploying Democratic CSI NFS driver..."
helm upgrade --install freenas-nfs democratic-csi/democratic-csi \
  --namespace democratic-csi \
  --values /Users/bret/git/homelab/k8s/democratic-csi/values-nfs.yaml \
  --set driver.config.httpConnection.host="$TRUENAS_HOST" \
  --set driver.config.httpConnection.apiKey="$TRUENAS_API_KEY" \
  --set driver.config.sshConnection.host="$TRUENAS_HOST" \
  --set driver.config.sshConnection.username="$TRUENAS_USERNAME" \
  --set driver.config.sshConnection.privateKey="$TRUENAS_SSH_KEY" \
  --wait \
  --timeout 5m

echo "Democratic CSI deployment complete!"
echo ""
echo "Checking pod status..."
kubectl --kubeconfig ~/.kube/config-kubespray get pods -n democratic-csi
echo ""
echo "Checking storage classes..."
kubectl --kubeconfig ~/.kube/config-kubespray get storageclass
