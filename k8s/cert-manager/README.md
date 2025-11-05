# Cert-manager Certificate Management

This directory contains the configuration for cert-manager, which provides automated certificate management for Kubernetes.

## Overview

cert-manager automates the lifecycle of TLS certificates:
- **Certificate Issuance**: Creates certificates automatically based on Certificate resources
- **Certificate Renewal**: Renews certificates before expiration
- **Multiple Issuers**: Supports various certificate authorities (CA, ACME, Vault, etc.)
- **Ingress Integration**: Automatically provisions certificates for Ingress resources

## Architecture

```
Certificate Request
       |
       v
ClusterIssuer/Issuer
       |
       v
Certificate Authority (CA, ACME, Vault, etc.)
       |
       v
Certificate (with TLS Secret)
       |
       v
Application/Ingress
```

## Prerequisites

### cert-manager Installation

cert-manager should be installed via kubespray addon or manually via Helm.

#### Installed by Kubespray

If you enabled cert-manager in kubespray configuration:

```yaml
# kubespray/inventory/homelab/group_vars/k8s_cluster/addons.yml
cert_manager_enabled: true
```

Verify installation:
```bash
kubectl get pods -n cert-manager

# Expected output:
# NAME                                      READY   STATUS    RESTARTS   AGE
# cert-manager-xxxxxxxxxx-xxxxx             1/1     Running   0          5m
# cert-manager-cainjector-xxxxxxxxxx-xxxxx  1/1     Running   0          5m
# cert-manager-webhook-xxxxxxxxxx-xxxxx     1/1     Running   0          5m
```

#### Manual Installation via Helm

If not installed by kubespray:

```bash
# Add Helm repository
helm repo add jetstack https://charts.jetstack.io
helm repo update

# Install cert-manager with CRDs
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true
```

## Configuration Files

### `cluster-issuer-selfsigned.yaml`
Creates a self-signed ClusterIssuer used to bootstrap the internal CA certificate.

### `internal-ca-cert.yaml`
Creates an internal CA certificate that will be used to sign all other certificates in the cluster.

**Key Features**:
- **10-year validity**: Long-lived CA certificate
- **4096-bit RSA key**: Strong encryption
- **isCA: true**: Marked as a Certificate Authority
- **Stored in**: `internal-ca-secret` in `cert-manager` namespace

### `cluster-issuer-ca.yaml`
Creates a CA ClusterIssuer that uses the internal CA to issue certificates for applications.

## Deployment

### Step-by-Step Setup

1. **Verify cert-manager Installation**:
```bash
kubectl get pods -n cert-manager
kubectl get crds | grep cert-manager
```

2. **Create Self-Signed ClusterIssuer**:
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/cert-manager/cluster-issuer-selfsigned.yaml
```

3. **Create Internal CA Certificate**:
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/cert-manager/internal-ca-cert.yaml
```

4. **Wait for CA Certificate to be Ready**:
```bash
kubectl wait --for=condition=ready certificate/internal-ca -n cert-manager --timeout=60s

# Check certificate status
kubectl get certificate -n cert-manager internal-ca
```

5. **Create CA ClusterIssuer**:
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/cert-manager/cluster-issuer-ca.yaml
```

6. **Verify ClusterIssuers**:
```bash
kubectl get clusterissuer

# Expected output:
# NAME                        READY   AGE
# selfsigned-cluster-issuer   True    2m
# ca-cluster-issuer           True    1m
```

### All-in-One Deployment

```bash
# Apply all cert-manager configurations
kubectl apply -f /Users/bret/git/homelab/k8s/cert-manager/

# Wait for CA certificate
kubectl wait --for=condition=ready certificate/internal-ca -n cert-manager --timeout=120s
```

## Verification

### Check ClusterIssuers

```bash
kubectl get clusterissuer

# Both should show READY=True
```

### Check Internal CA Certificate

```bash
# Check certificate status
kubectl get certificate -n cert-manager internal-ca

# Expected output:
# NAME          READY   SECRET                AGE
# internal-ca   True    internal-ca-secret    5m

# Describe certificate for details
kubectl describe certificate -n cert-manager internal-ca

# Verify secret created
kubectl get secret -n cert-manager internal-ca-secret
```

### View CA Certificate Details

```bash
# Extract and view the CA certificate
kubectl get secret -n cert-manager internal-ca-secret -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout

# Check expiration date
kubectl get secret -n cert-manager internal-ca-secret -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates
```

### Test Certificate Issuance

Create a test certificate:

```bash
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: test-certificate
  namespace: default
spec:
  secretName: test-tls-secret
  duration: 2160h  # 90 days
  renewBefore: 360h  # Renew 15 days before expiration
  subject:
    organizations:
      - Homelab Test
  commonName: test.lab.thewortmans.org
  isCA: false
  privateKey:
    algorithm: RSA
    encoding: PKCS1
    size: 2048
  usages:
    - server auth
    - client auth
  dnsNames:
    - test.lab.thewortmans.org
    - www.test.lab.thewortmans.org
  issuerRef:
    name: ca-cluster-issuer
    kind: ClusterIssuer
    group: cert-manager.io
EOF

# Check certificate status
kubectl get certificate test-certificate

# Expected: READY=True

# Verify secret created
kubectl get secret test-tls-secret

# Clean up test certificate
kubectl delete certificate test-certificate
kubectl delete secret test-tls-secret
```

## Usage

### Request Certificate via Certificate Resource

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: myapp-tls
  namespace: myapp
spec:
  secretName: myapp-tls-secret
  duration: 2160h  # 90 days
  renewBefore: 360h  # Renew 15 days before expiration
  subject:
    organizations:
      - Homelab
  commonName: myapp.lab.thewortmans.org
  isCA: false
  privateKey:
    algorithm: RSA
    size: 2048
  usages:
    - server auth
    - client auth
  dnsNames:
    - myapp.lab.thewortmans.org
  issuerRef:
    name: ca-cluster-issuer
    kind: ClusterIssuer
    group: cert-manager.io
```

### Automatic Certificate via Ingress Annotation

cert-manager can automatically create certificates for Ingress resources:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp-ingress
  namespace: myapp
  annotations:
    # Tell cert-manager to create a certificate
    cert-manager.io/cluster-issuer: ca-cluster-issuer
spec:
  tls:
  - hosts:
    - myapp.lab.thewortmans.org
    secretName: myapp-tls-cert  # cert-manager will create this secret
  rules:
  - host: myapp.lab.thewortmans.org
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: myapp-service
            port:
              number: 80
```

cert-manager will:
1. Detect the Ingress with the annotation
2. Create a Certificate resource automatically
3. Request the certificate from the CA ClusterIssuer
4. Store the certificate in the specified secret
5. Renew the certificate before expiration

### Wildcard Certificates

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: wildcard-lab-cert
  namespace: default
spec:
  secretName: wildcard-lab-tls
  duration: 2160h
  renewBefore: 360h
  commonName: "*.lab.thewortmans.org"
  dnsNames:
    - "*.lab.thewortmans.org"
    - lab.thewortmans.org
  issuerRef:
    name: ca-cluster-issuer
    kind: ClusterIssuer
```

### Namespace-scoped Issuer

For certificates within a single namespace:

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: ca-issuer
  namespace: myapp
spec:
  ca:
    secretName: internal-ca-secret  # Reference CA secret from cert-manager namespace
```

Note: The CA secret must be copied to the namespace or use a ClusterIssuer instead.

## Certificate Renewal

cert-manager automatically renews certificates based on the `renewBefore` setting:

```yaml
spec:
  duration: 2160h      # 90 days total validity
  renewBefore: 360h    # Renew 15 days (360 hours) before expiration
```

### Monitor Renewal Status

```bash
# Check all certificates
kubectl get certificate -A

# Check certificate events
kubectl describe certificate <cert-name> -n <namespace>

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager
```

### Force Renewal

Trigger manual renewal by deleting the secret:

```bash
# Delete the secret (cert-manager will recreate it)
kubectl delete secret <secret-name> -n <namespace>

# cert-manager will detect the missing secret and reissue the certificate
```

Or annotate the Certificate:

```bash
kubectl annotate certificate <cert-name> -n <namespace> cert-manager.io/issue-temporary-certificate="true" --overwrite
```

## Troubleshooting

### Certificate Not Ready

Check certificate status and events:
```bash
kubectl get certificate <cert-name> -n <namespace>
kubectl describe certificate <cert-name> -n <namespace>
```

Common issues:
- ClusterIssuer not ready
- CA secret not found
- Invalid DNS names or common name
- Insufficient RBAC permissions

### ClusterIssuer Not Ready

```bash
kubectl describe clusterissuer <issuer-name>
```

Check:
- CA secret exists in cert-manager namespace
- CA certificate is valid and not expired
- cert-manager pods are running

### Certificate Pending Forever

```bash
# Check CertificateRequest
kubectl get certificaterequest -n <namespace>
kubectl describe certificaterequest <request-name> -n <namespace>

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager -f
```

Common issues:
- ClusterIssuer misconfigured
- Network issues reaching external CA (if using ACME)
- Validation failures (DNS, HTTP challenges)

### Ingress Certificate Not Created

Verify:
1. cert-manager annotation is correct: `cert-manager.io/cluster-issuer: ca-cluster-issuer`
2. ClusterIssuer exists and is ready: `kubectl get clusterissuer`
3. Ingress has `tls` section with `hosts` and `secretName`
4. cert-manager webhook is running: `kubectl get pods -n cert-manager`

Check webhook logs:
```bash
kubectl logs -n cert-manager deployment/cert-manager-webhook
```

### CA Certificate Expired

If the internal CA expires, you'll need to:

1. Delete the expired CA certificate:
```bash
kubectl delete certificate internal-ca -n cert-manager
kubectl delete secret internal-ca-secret -n cert-manager
```

2. Recreate the CA:
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/cert-manager/internal-ca-cert.yaml
```

3. All certificates signed by the old CA will need to be renewed

## Trust Internal CA on Client Machines

To avoid browser warnings when accessing services with internal CA certificates:

### Linux

```bash
# Download CA certificate
kubectl get secret -n cert-manager internal-ca-secret -o jsonpath='{.data.tls\.crt}' | base64 -d > homelab-ca.crt

# Install CA certificate
sudo cp homelab-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

### macOS

```bash
# Download CA certificate
kubectl get secret -n cert-manager internal-ca-secret -o jsonpath='{.data.tls\.crt}' | base64 -d > homelab-ca.crt

# Add to keychain
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain homelab-ca.crt
```

### Windows

```bash
# Download CA certificate (using WSL or Git Bash)
kubectl get secret -n cert-manager internal-ca-secret -o jsonpath='{.data.tls\.crt}' | base64 -d > homelab-ca.crt

# Import certificate:
# 1. Double-click homelab-ca.crt
# 2. Click "Install Certificate"
# 3. Select "Local Machine"
# 4. Place in "Trusted Root Certification Authorities"
```

### Web Browsers

Some browsers use their own certificate store:

**Firefox**:
1. Settings > Privacy & Security > Certificates > View Certificates
2. Authorities tab > Import
3. Select `homelab-ca.crt`
4. Check "Trust this CA to identify websites"

**Chrome/Edge** (use system certificate store on most platforms)

## Advanced Configuration

### Multiple CAs for Different Purposes

Create separate CAs for different environments:

```yaml
# Development CA
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: dev-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: Homelab Development CA
  secretName: dev-ca-secret
  duration: 43800h  # 5 years
  issuerRef:
    name: selfsigned-cluster-issuer
    kind: ClusterIssuer
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: dev-ca-issuer
spec:
  ca:
    secretName: dev-ca-secret
```

### Integration with HashiCorp Vault

If you have Vault configured as a PKI backend:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: vault-issuer
spec:
  vault:
    server: https://192.168.10.101:8200
    path: pki/sign/homelab
    auth:
      tokenSecretRef:
        name: vault-token
        key: token
```

### ACME (Let's Encrypt) for Public Services

For public-facing services (requires DNS or HTTP validation):

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
    - http01:
        ingress:
          class: traefik
```

## Maintenance

### Backing Up CA Certificate

**IMPORTANT**: Back up the CA certificate and private key:

```bash
# Export CA certificate and key
kubectl get secret -n cert-manager internal-ca-secret -o yaml > internal-ca-backup.yaml

# Store securely (e.g., in Vault or encrypted backup)
# DO NOT commit this file to git!
```

### Monitoring Certificate Expiration

Check certificate expiration dates:

```bash
# List all certificates with expiration info
kubectl get certificate -A -o custom-columns=\
NAME:.metadata.name,\
NAMESPACE:.metadata.namespace,\
READY:.status.conditions[0].status,\
SECRET:.spec.secretName,\
ISSUER:.spec.issuerRef.name

# Check specific certificate expiration
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -noout -enddate
```

### Upgrading cert-manager

```bash
# Update Helm repo
helm repo update

# Upgrade cert-manager
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true

# Verify upgrade
kubectl rollout status deployment/cert-manager -n cert-manager
```

### Uninstalling cert-manager

```bash
# WARNING: This will remove all certificates

# Delete ClusterIssuers
kubectl delete clusterissuer --all

# Delete Certificates
kubectl delete certificate --all -A

# Uninstall Helm chart
helm uninstall cert-manager -n cert-manager

# Delete CRDs
kubectl delete crd certificates.cert-manager.io
kubectl delete crd certificaterequests.cert-manager.io
kubectl delete crd clusterissuers.cert-manager.io
kubectl delete crd issuers.cert-manager.io
kubectl delete crd orders.acme.cert-manager.io
kubectl delete crd challenges.acme.cert-manager.io

# Delete namespace
kubectl delete namespace cert-manager
```

## Integration with Traefik

Traefik automatically uses certificates provisioned by cert-manager:

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: myapp-ingressroute
  namespace: myapp
spec:
  entryPoints:
    - websecure
  routes:
  - match: Host(`myapp.lab.thewortmans.org`)
    kind: Rule
    services:
    - name: myapp-service
      port: 80
  tls:
    secretName: myapp-tls-cert  # Created by cert-manager
```

## Best Practices

1. **Use ClusterIssuers** for cluster-wide certificate issuance
2. **Set Appropriate Renewal Windows** (renew at 2/3 of certificate lifetime)
3. **Monitor Certificate Expiration** to avoid service outages
4. **Back Up CA Certificates** securely
5. **Use Long-Lived CA Certificates** (5-10 years) for stability
6. **Use Short-Lived Application Certificates** (90 days) for security
7. **Trust Internal CA on Client Machines** to avoid browser warnings
8. **Use Wildcard Certificates** sparingly (security vs. convenience trade-off)
9. **Separate CAs** for different environments (dev, staging, prod)
10. **Enable RBAC** to control who can request certificates

## References

- [cert-manager Official Documentation](https://cert-manager.io/docs/)
- [cert-manager Helm Chart](https://github.com/cert-manager/cert-manager/tree/master/deploy/charts/cert-manager)
- [Certificate Configuration](https://cert-manager.io/docs/configuration/)
- [Issuer Configuration](https://cert-manager.io/docs/configuration/issuers/)
- [Ingress Integration](https://cert-manager.io/docs/usage/ingress/)
