# MetalLB LoadBalancer Configuration

This directory contains the configuration for MetalLB, which provides LoadBalancer service type support for bare-metal Kubernetes clusters.

## Overview

MetalLB operates in Layer 2 (L2) mode to provide LoadBalancer IP addresses on the same network as the Kubernetes nodes. When a LoadBalancer service is created, MetalLB:
1. Assigns an IP address from the configured pool
2. Announces the IP via ARP (Layer 2)
3. Routes traffic to the appropriate service

## Prerequisites

### Network Requirements

- **IP Address Pool**: Reserve a range of IP addresses that are:
  - On the same subnet as your Kubernetes nodes (e.g., 192.168.100.0/24)
  - NOT managed by your DHCP server
  - Free for MetalLB to assign to services

- **kube-proxy Configuration**: Ensure `strictARP` is enabled in kube-proxy config (required for MetalLB L2 mode)

### Kubespray Configuration

If you deployed your cluster with kubespray, ensure the following in your group_vars:

```yaml
# kubespray/inventory/homelab/group_vars/k8s_cluster/k8s-cluster.yml
kube_proxy_strict_arp: true  # Required for MetalLB L2 mode
```

If you need to update kube-proxy after deployment:

```bash
kubectl edit configmap kube-proxy -n kube-system

# Set:
# strictARP: true

# Restart kube-proxy pods
kubectl rollout restart daemonset kube-proxy -n kube-system
```

## Configuration Files

### `namespace.yaml`
Creates the `metallb-system` namespace with appropriate pod security labels.

### `values.yaml`
Helm values for MetalLB deployment:
- Controller: Manages IP address assignments
- Speaker: DaemonSet that announces IPs via L2 (runs on all nodes)
- Tolerations configured to allow speaker on control plane nodes if needed

### `ipaddresspool.yaml`
Defines the IP address pool that MetalLB can assign to LoadBalancer services.

**Default Configuration**: `192.168.100.0/24`
- Update this to match your network configuration
- Ensure this range is available and not used by DHCP

### `l2advertisement.yaml`
Configures Layer 2 advertisement for the IP pool.

## Deployment

### Manual Deployment

1. **Create Namespace**:
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/metallb/namespace.yaml
```

2. **Add Helm Repository**:
```bash
helm repo add metallb https://metallb.github.io/metallb
helm repo update
```

3. **Deploy MetalLB**:
```bash
helm install metallb metallb/metallb \
  -n metallb-system \
  -f /Users/bret/git/homelab/k8s/metallb/values.yaml
```

4. **Wait for Pods to be Ready**:
```bash
kubectl wait --namespace metallb-system \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/name=metallb \
  --timeout=90s
```

5. **Apply IP Address Pool**:
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/metallb/ipaddresspool.yaml
```

6. **Apply L2 Advertisement**:
```bash
kubectl apply -f /Users/bret/git/homelab/k8s/metallb/l2advertisement.yaml
```

### Deployment via ArgoCD

Create an ArgoCD Application manifest (recommended for GitOps):

```yaml
# metallb-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: metallb
  namespace: argocd
spec:
  project: default
  destination:
    namespace: metallb-system
    server: https://kubernetes.default.svc
  sources:
    - repoURL: https://metallb.github.io/metallb
      targetRevision: 0.14.8
      chart: metallb
      helm:
        valueFiles:
          - $values/k8s/metallb/values.yaml
    - repoURL: git@github.com/wortmanb/homelab.git
      path: k8s/metallb
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
# Check MetalLB pods
kubectl get pods -n metallb-system

# Expected output:
# NAME                          READY   STATUS    RESTARTS   AGE
# metallb-controller-xxxxx      1/1     Running   0          2m
# metallb-speaker-xxxxx         1/1     Running   0          2m
# metallb-speaker-yyyyy         1/1     Running   0          2m
# metallb-speaker-zzzzz         1/1     Running   0          2m
```

### Check IP Address Pool

```bash
kubectl get ipaddresspool -n metallb-system

# Expected output:
# NAME           AGE
# default-pool   5m
```

### Check L2 Advertisement

```bash
kubectl get l2advertisement -n metallb-system

# Expected output:
# NAME               AGE
# default-l2advert   5m
```

### Test LoadBalancer Service

Deploy a test nginx service with LoadBalancer type:

```bash
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-test
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nginx-test
  template:
    metadata:
      labels:
        app: nginx-test
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: nginx-test-lb
  namespace: default
spec:
  type: LoadBalancer
  selector:
    app: nginx-test
  ports:
  - port: 80
    targetPort: 80
    protocol: TCP
EOF

# Check service for assigned external IP
kubectl get svc nginx-test-lb

# Expected output:
# NAME            TYPE           CLUSTER-IP      EXTERNAL-IP      PORT(S)        AGE
# nginx-test-lb   LoadBalancer   10.233.x.x      192.168.100.1    80:30123/TCP   1m

# Test connectivity from your network
curl http://192.168.100.1

# Clean up test resources
kubectl delete deployment nginx-test
kubectl delete service nginx-test-lb
```

## Troubleshooting

### Controller Pod Not Running

Check controller logs:
```bash
kubectl logs -n metallb-system deployment/metallb-controller
```

Common issues:
- RBAC permissions missing
- Unable to watch for services/endpoints
- API server connectivity issues

### Speaker Pods Not Running

Check speaker logs:
```bash
kubectl logs -n metallb-system daemonset/metallb-speaker
```

Common issues:
- Node network configuration issues
- Missing network interface
- Insufficient privileges (check pod security policies)

### LoadBalancer Service Stuck in Pending

```bash
# Check service events
kubectl describe svc <service-name>

# Check MetalLB controller logs
kubectl logs -n metallb-system deployment/metallb-controller
```

Common issues:
- IPAddressPool not configured or empty
- All IPs in pool already allocated
- L2Advertisement not configured
- Speaker pods not running on any node

### External IP Not Reachable

1. **Verify IP Assignment**:
```bash
kubectl get svc <service-name> -o wide
```

2. **Check ARP Table** (from another machine on the network):
```bash
# On Linux/Mac
arp -a | grep <external-ip>

# On Windows
arp -a | findstr <external-ip>
```

3. **Check Speaker Logs**:
```bash
kubectl logs -n metallb-system daemonset/metallb-speaker
```

4. **Verify strictARP** is enabled:
```bash
kubectl get configmap kube-proxy -n kube-system -o yaml | grep strictARP
```

Common issues:
- Firewall blocking traffic
- IP range not on same L2 network as nodes
- strictARP not enabled in kube-proxy
- Network switch blocking ARP announcements

### Multiple IPs Assigned to Same Service

This indicates a split-brain scenario. Check:
```bash
kubectl get endpoints <service-name>
kubectl logs -n metallb-system deployment/metallb-controller
```

### IP Address Conflicts

If you see IP conflicts with existing devices:
1. Update the IPAddressPool range to use free IPs
2. Delete and recreate the service to get a new IP

```bash
# Update ipaddresspool.yaml with new range
kubectl apply -f /Users/bret/git/homelab/k8s/metallb/ipaddresspool.yaml

# Delete service (if IP conflict occurred)
kubectl delete svc <service-name>

# Recreate service
kubectl apply -f <service-manifest.yaml>
```

## IP Address Pool Management

### View Current IP Allocations

```bash
# List all LoadBalancer services and their IPs
kubectl get svc -A -o wide | grep LoadBalancer
```

### Reserve Specific IPs

Assign a specific IP to a service using annotation:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
  annotations:
    metallb.universe.tf/loadBalancerIPs: 192.168.100.50
spec:
  type: LoadBalancer
  selector:
    app: my-app
  ports:
  - port: 80
```

### Multiple IP Address Pools

Create additional pools for different purposes:

```yaml
# ipaddresspool-dmz.yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: dmz-pool
  namespace: metallb-system
spec:
  addresses:
    - 192.168.200.0/28
  autoAssign: false  # Only assign when explicitly requested
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: dmz-l2advert
  namespace: metallb-system
spec:
  ipAddressPools:
    - dmz-pool
```

Use specific pool in service annotation:

```yaml
metadata:
  annotations:
    metallb.universe.tf/address-pool: dmz-pool
```

## Advanced Configuration

### Sharing IPs Between Services

MetalLB supports IP sharing when services use different ports:

```yaml
# Service 1 - HTTP
metadata:
  annotations:
    metallb.universe.tf/allow-shared-ip: "shared-key"
spec:
  type: LoadBalancer
  ports:
  - port: 80
    protocol: TCP
---
# Service 2 - HTTPS (shares same IP)
metadata:
  annotations:
    metallb.universe.tf/allow-shared-ip: "shared-key"
spec:
  type: LoadBalancer
  ports:
  - port: 443
    protocol: TCP
```

### Node Selectors for L2 Advertisement

Limit which nodes can announce IPs (useful for multi-zone deployments):

```yaml
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: zone-a-l2advert
  namespace: metallb-system
spec:
  ipAddressPools:
    - zone-a-pool
  nodeSelectors:
    - matchLabels:
        topology.kubernetes.io/zone: zone-a
```

## Maintenance

### Upgrading MetalLB

```bash
# Update Helm repo
helm repo update

# Check current version
helm list -n metallb-system

# Upgrade
helm upgrade metallb metallb/metallb \
  -n metallb-system \
  -f /Users/bret/git/homelab/k8s/metallb/values.yaml

# Verify upgrade
kubectl rollout status deployment/metallb-controller -n metallb-system
kubectl rollout status daemonset/metallb-speaker -n metallb-system
```

### Uninstalling MetalLB

```bash
# WARNING: This will remove all LoadBalancer IP assignments

# Delete IP pools and advertisements first
kubectl delete -f /Users/bret/git/homelab/k8s/metallb/l2advertisement.yaml
kubectl delete -f /Users/bret/git/homelab/k8s/metallb/ipaddresspool.yaml

# Uninstall Helm chart
helm uninstall metallb -n metallb-system

# Delete namespace
kubectl delete namespace metallb-system
```

## Integration with Other Components

### With Traefik Ingress

MetalLB assigns an IP to Traefik's LoadBalancer service, making Traefik accessible from outside the cluster:

```bash
# Check Traefik LoadBalancer IP
kubectl get svc -n traefik traefik

# Update DNS to point to this IP
# Example: *.lab.thewortmans.org -> 192.168.100.10
```

### With cert-manager

No special configuration needed. Services with LoadBalancer IPs work normally with cert-manager certificates.

## References

- [MetalLB Official Documentation](https://metallb.universe.tf/)
- [MetalLB Helm Chart](https://github.com/metallb/metallb/tree/main/charts/metallb)
- [MetalLB L2 Configuration](https://metallb.universe.tf/configuration/l2/)
- [Kubernetes Service Type LoadBalancer](https://kubernetes.io/docs/concepts/services-networking/service/#loadbalancer)
