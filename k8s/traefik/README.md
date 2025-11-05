# Traefik Ingress Controller Configuration

This directory contains the configuration for Traefik, a modern HTTP reverse proxy and load balancer that serves as the Ingress Controller for the Kubernetes cluster.

## Overview

Traefik provides:
- **Ingress Controller**: Routes HTTP/HTTPS traffic to services based on hostname and path
- **Load Balancing**: Distributes traffic across multiple pod replicas
- **TLS Termination**: Handles SSL/TLS certificates (integrates with cert-manager)
- **Dashboard**: Web UI for monitoring routes and services
- **Middleware**: Request/response transformations, authentication, rate limiting, etc.

## Architecture

```
Internet/Network
      |
      v
  MetalLB (LoadBalancer IP)
      |
      v
  Traefik Service (LoadBalancer)
      |
      v
  Traefik Pods (Deployment with 2 replicas)
      |
      v
  Backend Services (via Ingress or IngressRoute)
```

## Prerequisites

### MetalLB LoadBalancer

Traefik requires MetalLB (or another LoadBalancer implementation) to be deployed and operational. The Traefik service will be assigned an external IP from the MetalLB pool.

Verify MetalLB is running:
```bash
kubectl get pods -n metallb-system
kubectl get ipaddresspool -n metallb-system
```

### cert-manager (Optional)

For automatic TLS certificate management, deploy cert-manager before Traefik:
```bash
kubectl get pods -n cert-manager
```

## Configuration Files

### `namespace.yaml`
Creates the `traefik` namespace for all Traefik components.

### `values.yaml`
Helm values for Traefik deployment:
- **Service Type**: LoadBalancer (uses MetalLB)
- **Ports**: HTTP (80), HTTPS (443), Dashboard (9000)
- **Replicas**: 2 for high availability
- **Providers**: Kubernetes Ingress and IngressRoute CRD support
- **Dashboard**: Enabled at `/dashboard` endpoint

## Deployment

### Manual Deployment

1. **Create Namespace**:
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/traefik/namespace.yaml
```

2. **Add Helm Repository**:
```bash
helm repo add traefik https://traefik.github.io/charts
helm repo update
```

3. **Deploy Traefik**:
```bash
helm install traefik traefik/traefik \
  -n traefik \
  -f /Users/bret/git/homelab/k8s/traefik/values.yaml
```

4. **Wait for Deployment**:
```bash
kubectl wait --namespace traefik \
  --for=condition=available deployment/traefik \
  --timeout=90s
```

### Deployment via ArgoCD

Create an ArgoCD Application manifest (recommended for GitOps):

```yaml
# traefik-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: traefik
  namespace: argocd
spec:
  project: default
  destination:
    namespace: traefik
    server: https://kubernetes.default.svc
  sources:
    - repoURL: https://traefik.github.io/charts
      targetRevision: 30.0.2
      chart: traefik
      helm:
        valueFiles:
          - $values/k8s/traefik/values.yaml
    - repoURL: git@github.com/wortmanb/homelab.git
      path: k8s/traefik
      targetRevision: main
      ref: values
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
    automated: {}
```

## Verification

### Check Deployment Status

```bash
# Check Traefik pods
kubectl get pods -n traefik

# Expected output:
# NAME                       READY   STATUS    RESTARTS   AGE
# traefik-xxxxxxxxxx-xxxxx   1/1     Running   0          2m
# traefik-xxxxxxxxxx-yyyyy   1/1     Running   0          2m
```

### Check LoadBalancer IP

```bash
kubectl get svc -n traefik

# Expected output:
# NAME      TYPE           CLUSTER-IP      EXTERNAL-IP       PORT(S)
# traefik   LoadBalancer   10.233.x.x      192.168.100.10    80:30080/TCP,443:30443/TCP,9000:30900/TCP
```

Note the `EXTERNAL-IP` assigned by MetalLB - this is your Ingress IP address.

### Access Traefik Dashboard

1. **Via Port Forward** (for initial testing):
```bash
kubectl port-forward -n traefik deployment/traefik 9000:9000
```
Then access: `http://localhost:9000/dashboard/`

2. **Via LoadBalancer IP**:
```bash
# Get the LoadBalancer IP
TRAEFIK_IP=$(kubectl get svc -n traefik traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "Traefik Dashboard: http://${TRAEFIK_IP}:9000/dashboard/"
```

Access: `http://192.168.100.10:9000/dashboard/` (replace with your actual IP)

3. **Via Ingress** (recommended for production):

Create an Ingress for the dashboard:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: traefik-dashboard
  namespace: traefik
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: web
spec:
  rules:
  - host: traefik.lab.thewortmans.org
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: api@internal
            port:
              name: traefik
```

## Usage

### Standard Kubernetes Ingress

Traefik supports standard Kubernetes Ingress resources:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
  namespace: default
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: web
spec:
  rules:
  - host: myapp.lab.thewortmans.org
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-app-service
            port:
              number: 80
```

### TLS/HTTPS Ingress

With cert-manager integration:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress-tls
  namespace: default
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    cert-manager.io/cluster-issuer: ca-cluster-issuer
spec:
  tls:
  - hosts:
    - myapp.lab.thewortmans.org
    secretName: myapp-tls-cert
  rules:
  - host: myapp.lab.thewortmans.org
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-app-service
            port:
              number: 80
```

### Traefik IngressRoute (CRD)

Traefik's native IngressRoute CRD provides more advanced features:

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app-ingressroute
  namespace: default
spec:
  entryPoints:
    - web
  routes:
  - match: Host(`myapp.lab.thewortmans.org`)
    kind: Rule
    services:
    - name: my-app-service
      port: 80
```

### IngressRoute with TLS

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app-ingressroute-tls
  namespace: default
spec:
  entryPoints:
    - websecure
  routes:
  - match: Host(`myapp.lab.thewortmans.org`)
    kind: Rule
    services:
    - name: my-app-service
      port: 80
  tls:
    secretName: myapp-tls-cert
```

### Middleware Examples

Traefik Middleware allows request/response transformations:

#### Redirect HTTP to HTTPS

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: https-redirect
  namespace: default
spec:
  redirectScheme:
    scheme: https
    permanent: true
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app-http-redirect
  namespace: default
spec:
  entryPoints:
    - web
  routes:
  - match: Host(`myapp.lab.thewortmans.org`)
    kind: Rule
    middlewares:
      - name: https-redirect
    services:
    - name: my-app-service
      port: 80
```

#### Basic Authentication

```yaml
# Create htpasswd secret
htpasswd -c auth admin
kubectl create secret generic authsecret --from-file=users=auth -n default
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: basic-auth
  namespace: default
spec:
  basicAuth:
    secret: authsecret
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: my-app-protected
  namespace: default
spec:
  entryPoints:
    - websecure
  routes:
  - match: Host(`myapp.lab.thewortmans.org`)
    kind: Rule
    middlewares:
      - name: basic-auth
    services:
    - name: my-app-service
      port: 80
  tls:
    secretName: myapp-tls-cert
```

#### Rate Limiting

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: rate-limit
  namespace: default
spec:
  rateLimit:
    average: 100
    burst: 50
```

#### Path Prefix Strip

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: strip-prefix
  namespace: default
spec:
  stripPrefix:
    prefixes:
      - /api
```

## Troubleshooting

### Traefik Pods Not Starting

Check pod events and logs:
```bash
kubectl describe pod -n traefik <pod-name>
kubectl logs -n traefik <pod-name>
```

Common issues:
- Insufficient resources
- RBAC permissions missing
- Port conflicts

### LoadBalancer IP Stuck in Pending

Verify MetalLB is operational:
```bash
kubectl get pods -n metallb-system
kubectl get ipaddresspool -n metallb-system
```

Check MetalLB logs:
```bash
kubectl logs -n metallb-system deployment/metallb-controller
```

### Ingress Not Routing Traffic

1. **Check Ingress Status**:
```bash
kubectl get ingress -A
kubectl describe ingress <ingress-name> -n <namespace>
```

2. **Check Traefik Logs**:
```bash
kubectl logs -n traefik deployment/traefik
```

3. **Verify Backend Service**:
```bash
kubectl get svc <service-name> -n <namespace>
kubectl get endpoints <service-name> -n <namespace>
```

4. **Check Traefik Dashboard** for routing table and service status

Common issues:
- Hostname mismatch in Ingress rule
- Backend service not found or no endpoints
- TLS certificate issues
- Middleware misconfiguration

### TLS Certificate Issues

Check certificate status:
```bash
kubectl get certificate -A
kubectl describe certificate <cert-name> -n <namespace>
```

Check cert-manager logs:
```bash
kubectl logs -n cert-manager deployment/cert-manager
```

### 404 or 503 Errors

- **404**: No matching route found
  - Verify Ingress/IngressRoute match rules
  - Check hostname and path configuration
  - Inspect Traefik dashboard routing table

- **503**: Service unavailable
  - Backend service has no ready endpoints
  - Check pod status: `kubectl get pods -n <namespace>`
  - Verify service selector matches pod labels

## DNS Configuration

### Update DNS Records

Point your domain/subdomains to the Traefik LoadBalancer IP:

```bash
# Get Traefik LoadBalancer IP
kubectl get svc -n traefik traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
```

**Example DNS records** (in your local DNS server or hosts file):

```
192.168.100.10  myapp.lab.thewortmans.org
192.168.100.10  webapp.lab.thewortmans.org
192.168.100.10  *.lab.thewortmans.org   # Wildcard for all subdomains
```

### Local Testing with /etc/hosts

For local testing without DNS:

```bash
# /etc/hosts (Linux/Mac) or C:\Windows\System32\drivers\etc\hosts (Windows)
192.168.100.10  myapp.lab.thewortmans.org
192.168.100.10  webapp.lab.thewortmans.org
```

## Maintenance

### Upgrading Traefik

```bash
# Update Helm repo
helm repo update

# Check current version
helm list -n traefik

# Upgrade Traefik
helm upgrade traefik traefik/traefik \
  -n traefik \
  -f /Users/bret/git/homelab/k8s/traefik/values.yaml

# Verify upgrade
kubectl rollout status deployment/traefik -n traefik
```

### Viewing Logs

```bash
# Real-time logs
kubectl logs -n traefik deployment/traefik -f

# Access logs (JSON format)
kubectl logs -n traefik deployment/traefik | jq '.msg'
```

### Scaling Traefik

Adjust replicas in `values.yaml` or directly:

```bash
kubectl scale deployment traefik -n traefik --replicas=3
```

### Uninstalling Traefik

```bash
# WARNING: This will remove all Ingress routing

# Uninstall Helm chart
helm uninstall traefik -n traefik

# Delete namespace
kubectl delete namespace traefik
```

## Integration with Other Components

### With cert-manager

cert-manager automatically provisions TLS certificates for Ingress resources:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  annotations:
    cert-manager.io/cluster-issuer: ca-cluster-issuer
spec:
  tls:
  - hosts:
    - myapp.lab.thewortmans.org
    secretName: myapp-tls
```

### With External Secrets Operator

Use ExternalSecrets to inject secrets into Traefik middleware (e.g., for basic auth):

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: traefik-auth
  namespace: default
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: traefik-auth-secret
  data:
  - secretKey: users
    remoteRef:
      key: secret/homelab/traefik/basicauth
      property: htpasswd
```

### With ArgoCD

Deploy applications with Ingress via ArgoCD for full GitOps workflow.

## Best Practices

1. **Use IngressRoute CRD** for advanced features instead of standard Ingress
2. **Enable HTTPS** for all production services using cert-manager
3. **Implement Rate Limiting** on public-facing services
4. **Use Middleware** for cross-cutting concerns (auth, redirects, headers)
5. **Monitor Dashboard** regularly for routing and performance issues
6. **Set Resource Limits** to prevent resource exhaustion
7. **Enable Access Logs** during troubleshooting, disable in production for performance
8. **Use Multiple Replicas** for high availability
9. **Configure Health Checks** for proper load balancing
10. **Secure Dashboard Access** using authentication or restrict to internal network

## References

- [Traefik Official Documentation](https://doc.traefik.io/traefik/)
- [Traefik Helm Chart](https://github.com/traefik/traefik-helm-chart)
- [Traefik Kubernetes CRD](https://doc.traefik.io/traefik/routing/providers/kubernetes-crd/)
- [Traefik Middleware](https://doc.traefik.io/traefik/middlewares/overview/)
- [Traefik with cert-manager](https://doc.traefik.io/traefik/https/acme/#cert-manager)
