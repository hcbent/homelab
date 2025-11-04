# External Secrets Operator - Deployment Instructions

This guide provides step-by-step instructions to deploy and configure External Secrets Operator (ESO) in your homelab Kubernetes cluster.

## Prerequisites Checklist

- [ ] Kubernetes cluster is running and accessible
- [ ] HashiCorp Vault is running at https://192.168.10.101:8200
- [ ] You have a Vault token with `apps` policy (or similar)
- [ ] ArgoCD is deployed and operational
- [ ] `kubectl` is configured to access your cluster
- [ ] All secrets are stored in Vault under `secret/homelab/*` paths

## Deployment Steps

### Step 1: Verify Vault Accessibility

First, ensure your Kubernetes cluster can reach Vault:

```bash
# Test from your local machine
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_TOKEN="<your-vault-token>"
vault status

# Test from within the cluster
kubectl run vault-test --rm -it --restart=Never --image=vault:latest -- \
  vault status -address=https://192.168.10.101:8200 -tls-skip-verify
```

Expected output: Vault status showing it's initialized and unsealed.

### Step 2: Verify Secrets in Vault

Confirm all required secrets are in Vault:

```bash
# List secrets
vault kv list secret/homelab

# Verify a few key secrets
vault kv get secret/homelab/pihole/lab/credentials
vault kv get secret/homelab/prometheus/lab/credentials
vault kv get secret/homelab/freenas/credentials
```

### Step 3: Deploy External Secrets Operator

Deploy ESO using ArgoCD:

```bash
# Navigate to the repository root
cd /Users/bret/git/homelab

# Apply the ArgoCD application
kubectl apply -f k8s/external-secrets-app.yaml

# Watch the deployment
kubectl get application external-secrets -n argocd -w
```

Wait for the application to show `Healthy` and `Synced` status (Ctrl+C to exit watch).

```bash
# Verify ESO pods are running
kubectl get pods -n external-secrets-system

# Expected output:
# NAME                                                READY   STATUS    RESTARTS   AGE
# external-secrets-xxxxx                              1/1     Running   0          2m
# external-secrets-cert-controller-xxxxx              1/1     Running   0          2m
# external-secrets-webhook-xxxxx                      1/1     Running   0          2m

# Wait for all deployments to be ready
kubectl wait --for=condition=available --timeout=300s \
  deployment/external-secrets -n external-secrets-system
kubectl wait --for=condition=available --timeout=300s \
  deployment/external-secrets-webhook -n external-secrets-system
kubectl wait --for=condition=available --timeout=300s \
  deployment/external-secrets-cert-controller -n external-secrets-system
```

### Step 4: Create Vault Token Secret

Create a Kubernetes secret containing the Vault token for ESO to authenticate:

```bash
# Option A: Using an existing long-lived token
kubectl create secret generic vault-token \
  -n external-secrets-system \
  --from-literal=token="<your-vault-token>"

# Option B: Create a new token specifically for ESO
export VAULT_ADDR="https://192.168.10.101:8200"
export VAULT_TOKEN="<your-admin-token>"

# Create a token with the apps policy, valid for 1 year
NEW_TOKEN=$(vault token create -policy=apps -ttl=8760h -format=json | jq -r '.auth.client_token')
echo "New ESO token: $NEW_TOKEN"

# Store it in Kubernetes
kubectl create secret generic vault-token \
  -n external-secrets-system \
  --from-literal=token="$NEW_TOKEN"

# Verify the secret was created
kubectl get secret vault-token -n external-secrets-system
```

### Step 5: Deploy ClusterSecretStore

Deploy the Vault backend configuration:

```bash
# IMPORTANT: First edit vault-secret-store.yaml to remove the placeholder token
# The actual token should already be in the vault-token secret from Step 4

# Apply the ClusterSecretStore
kubectl apply -f k8s/external-secrets/vault-secret-store.yaml

# Verify the SecretStore is ready
kubectl get clustersecretstore vault-backend

# Expected output:
# NAME            AGE   STATUS   CAPABILITIES   READY
# vault-backend   10s   Valid    ReadWrite      True

# If not ready, check the status
kubectl describe clustersecretstore vault-backend
```

If the ClusterSecretStore shows errors, check:
- Vault is accessible from the cluster
- The Vault token is valid
- The token has appropriate permissions

### Step 6: Create Required Namespaces

Ensure all target namespaces exist:

```bash
# Create namespaces if they don't exist
kubectl create namespace pihole --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace elastic-stack --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace prometheus --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace democratic-csi --dry-run=client -o yaml | kubectl apply -f -

# Verify
kubectl get namespaces | grep -E 'pihole|elastic-stack|prometheus|democratic-csi'
```

### Step 7: Deploy ExternalSecret Resources

Deploy ExternalSecrets for each service:

```bash
# Pi-hole
kubectl apply -f k8s/pihole/external-secret.yaml
kubectl get externalsecret pihole-secret -n pihole

# Paperless
kubectl apply -f k8s/paperless/external-secret.yaml
kubectl get externalsecret paperless-db-secret -n default

# Cerebro
kubectl apply -f k8s/cerebro/external-secret.yaml
kubectl get externalsecret cerebro-secret -n elastic-stack

# Prometheus/Grafana
kubectl apply -f k8s/prometheus/external-secret.yaml
kubectl get externalsecret prometheus-grafana-secret -n prometheus

# Democratic CSI (FreeNAS)
kubectl apply -f k8s/freenas/external-secret.yaml
kubectl get externalsecret freenas-credentials -n democratic-csi

# Unpackerr
kubectl apply -f k8s/unpackerr/external-secret.yaml
kubectl get externalsecret unpackerr-secret -n default

# Wait a few seconds for ESO to sync
sleep 10
```

### Step 8: Verify Secret Synchronization

Check that all secrets were created successfully:

```bash
# List all ExternalSecrets
kubectl get externalsecret -A

# Expected output: All should show READY=True
# NAMESPACE         NAME                        STORE           REFRESH INTERVAL   STATUS         READY
# pihole            pihole-secret               vault-backend   1h                 SecretSynced   True
# default           paperless-db-secret         vault-backend   1h                 SecretSynced   True
# elastic-stack     cerebro-secret              vault-backend   1h                 SecretSynced   True
# prometheus        prometheus-grafana-secret   vault-backend   1h                 SecretSynced   True
# democratic-csi    freenas-credentials         vault-backend   1h                 SecretSynced   True
# default           unpackerr-secret            vault-backend   1h                 SecretSynced   True

# Verify the Kubernetes secrets were created
kubectl get secret pihole-secret -n pihole
kubectl get secret paperless-db-secret -n default
kubectl get secret cerebro-secret -n elastic-stack
kubectl get secret prometheus-grafana-secret -n prometheus
kubectl get secret freenas-credentials -n democratic-csi
kubectl get secret unpackerr-secret -n default

# Check a specific secret's contents (example)
kubectl get secret pihole-secret -n pihole -o jsonpath='{.data.WEBPASSWORD}' | base64 -d
echo ""  # newline
```

### Step 9: Update Application Manifests

The application manifests have already been updated to use the auto-generated secrets. Deploy or restart the applications:

```bash
# Pi-hole
kubectl apply -f k8s/pihole/pihole.yaml
kubectl rollout status deployment/pihole -n pihole

# Cerebro
kubectl apply -f k8s/cerebro/cerebro.yaml
kubectl rollout status deployment/cerebro -n elastic-stack

# Unpackerr
kubectl apply -f k8s/home-apps/unpackerr-deployment.yaml
kubectl rollout status deployment/unpackerr -n default

# For Helm-based deployments (Prometheus, Democratic CSI, Paperless)
# These will be updated when you next run helm upgrade or ArgoCD syncs
```

### Step 10: Verify Applications

Verify that applications are using the secrets correctly:

```bash
# Check Pi-hole deployment
kubectl get pods -n pihole
kubectl describe pod -n pihole -l app=pihole | grep -A5 "Environment"

# Check Cerebro
kubectl get pods -n elastic-stack
kubectl logs -n elastic-stack deployment/cerebro | head -20

# Check that no errors appear related to secrets
kubectl get events -n pihole --field-selector type=Warning
kubectl get events -n elastic-stack --field-selector type=Warning
```

## Post-Deployment Verification

### Test Secret Rotation

Verify that ESO can detect and sync secret changes:

```bash
# Update a secret in Vault
vault kv put secret/homelab/pihole/lab/credentials \
    webpassword=new-test-password

# Force immediate sync (don't wait for refresh interval)
kubectl annotate externalsecret pihole-secret -n pihole \
  force-sync=$(date +%s) --overwrite

# Wait a few seconds
sleep 5

# Verify the secret was updated
kubectl get secret pihole-secret -n pihole -o jsonpath='{.data.WEBPASSWORD}' | base64 -d
echo ""

# Restart the pod to use the new secret
kubectl rollout restart deployment/pihole -n pihole

# Don't forget to change the password back if this was just a test!
vault kv put secret/homelab/pihole/lab/credentials \
    webpassword=<original-password>
```

### Monitor ESO Metrics

Check that ESO is functioning properly:

```bash
# Port-forward to access metrics
kubectl port-forward -n external-secrets-system deployment/external-secrets 8080:8080 &

# View metrics (in another terminal or after backgrounding)
curl http://localhost:8080/metrics | grep externalsecret

# Stop port-forward
kill %1
```

### Check Logs

Review ESO logs for any issues:

```bash
# Main operator logs
kubectl logs -n external-secrets-system deployment/external-secrets --tail=50

# Webhook logs
kubectl logs -n external-secrets-system deployment/external-secrets-webhook --tail=50

# Cert controller logs
kubectl logs -n external-secrets-system deployment/external-secrets-cert-controller --tail=50
```

## Troubleshooting

### ExternalSecret Shows "SecretSyncedError"

```bash
# Get detailed status
kubectl describe externalsecret <name> -n <namespace>

# Common issues:
# 1. Secret doesn't exist in Vault
vault kv get secret/homelab/path/to/secret

# 2. Wrong path specified
# Check the 'key' field in the ExternalSecret matches Vault path

# 3. Vault token lacks permissions
vault token capabilities secret/data/homelab/path/to/secret
```

### ClusterSecretStore Not Ready

```bash
# Check SecretStore status
kubectl describe clustersecretstore vault-backend

# Verify Vault token
kubectl get secret vault-token -n external-secrets-system -o jsonpath='{.data.token}' | base64 -d
# Copy the token and test it:
export VAULT_TOKEN="<token-from-above>"
vault token lookup

# Test connectivity to Vault from cluster
kubectl run vault-test --rm -it --restart=Never --image=vault:latest -- \
  vault status -address=https://192.168.10.101:8200 -tls-skip-verify
```

### Secrets Not Appearing in Pods

```bash
# 1. Verify secret exists
kubectl get secret <secret-name> -n <namespace>

# 2. Check secret contents
kubectl get secret <secret-name> -n <namespace> -o yaml

# 3. Verify pod is referencing the secret correctly
kubectl get deployment <deployment-name> -n <namespace> -o yaml | grep -A10 "secretRef"

# 4. Restart the deployment
kubectl rollout restart deployment/<deployment-name> -n <namespace>
```

## Rollback Procedure

If you need to rollback to manual secrets:

```bash
# 1. Delete ExternalSecret resources
kubectl delete externalsecret --all -A

# 2. Delete ClusterSecretStore
kubectl delete clustersecretstore vault-backend

# 3. Create manual secrets
kubectl create secret generic pihole-secret -n pihole \
  --from-literal=WEBPASSWORD="<password>"

# 4. Applications will continue using the manually created secrets
```

## Next Steps

After successful deployment:

1. **Set up monitoring**: Configure Prometheus to scrape ESO metrics
2. **Configure alerts**: Set up alerts for failed secret syncs
3. **Migrate to Kubernetes auth**: Replace token auth with Kubernetes auth method (see EXTERNAL-SECRETS-SETUP.md)
4. **Document rotation procedures**: Create runbooks for secret rotation
5. **Test disaster recovery**: Practice recovering from ESO failure scenarios

## Maintenance Schedule

- **Weekly**: Review ESO logs for errors
- **Monthly**: Verify all ExternalSecrets are syncing (check READY status)
- **Quarterly**: Rotate Vault token used by ESO
- **Annually**: Review and update ESO version

## Support

For issues or questions:
1. Check [EXTERNAL-SECRETS-SETUP.md](./EXTERNAL-SECRETS-SETUP.md) for detailed documentation
2. Review ESO logs: `kubectl logs -n external-secrets-system deployment/external-secrets`
3. Check [External Secrets Operator Documentation](https://external-secrets.io/)
4. Search [GitHub Issues](https://github.com/external-secrets/external-secrets/issues)
