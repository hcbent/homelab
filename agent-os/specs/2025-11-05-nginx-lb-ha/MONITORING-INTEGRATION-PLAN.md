# Nginx Load Balancer HA - Monitoring Integration Plan

This document outlines the monitoring strategy for the nginx load balancer HA cluster, including metrics collection, alerting rules, and dashboard creation for integration with the existing Prometheus/Grafana stack.

## Overview

The nginx load balancer HA cluster requires comprehensive monitoring to ensure high availability and early detection of issues. This plan leverages the existing Prometheus and Grafana infrastructure deployed in the Kubernetes cluster.

## Architecture

### Monitoring Components

**Data Collection:**
- Nginx Exporter (nginx-prometheus-exporter) for nginx metrics
- Node Exporter for system-level metrics
- Custom scripts for Corosync/Pacemaker cluster status
- Blackbox Exporter for VIP availability probing

**Data Storage:**
- Existing Prometheus instance in prometheus namespace
- Retention policy aligned with cluster standards

**Visualization:**
- Grafana dashboards in prometheus namespace
- Pre-built dashboards for nginx and cluster health

**Alerting:**
- Prometheus AlertManager for alert routing
- Integration with existing alert channels (email, Slack, etc.)

## Metrics to Collect

### 1. Nginx Metrics

**Service Status:**
```promql
# Nginx service up/down status
nginx_up{instance=~"nginx-lb.*"}

# Nginx version info
nginx_version_info{instance=~"nginx-lb.*"}
```

**Connection Metrics:**
```promql
# Active connections
nginx_connections_active{instance=~"nginx-lb.*"}

# Waiting connections
nginx_connections_waiting{instance=~"nginx-lb.*"}

# Reading/writing connections
nginx_connections_reading{instance=~"nginx-lb.*"}
nginx_connections_writing{instance=~"nginx-lb.*"}

# Accepted/handled connections
rate(nginx_connections_accepted_total{instance=~"nginx-lb.*"}[5m])
rate(nginx_connections_handled_total{instance=~"nginx-lb.*"}[5m])
```

**Request Metrics:**
```promql
# Total requests
rate(nginx_http_requests_total{instance=~"nginx-lb.*"}[5m])

# Requests by status code
rate(nginx_http_requests_total{instance=~"nginx-lb.*",status=~"2.."}[5m])
rate(nginx_http_requests_total{instance=~"nginx-lb.*",status=~"4.."}[5m])
rate(nginx_http_requests_total{instance=~"nginx-lb.*",status=~"5.."}[5m])
```

**Upstream (Backend) Metrics:**
```promql
# Upstream status (per backend)
nginx_upstream_up{instance=~"nginx-lb.*",upstream=~"k8s_api_servers|argocd.*|traefik.*"}

# Upstream active connections
nginx_upstream_connections{instance=~"nginx-lb.*",state="active"}

# Upstream response times
histogram_quantile(0.95, rate(nginx_upstream_response_time_seconds_bucket{instance=~"nginx-lb.*"}[5m]))

# Upstream health check status
nginx_upstream_healthchecks_checks_total{instance=~"nginx-lb.*"}
nginx_upstream_healthchecks_unhealthy_total{instance=~"nginx-lb.*"}
```

**Stream (K8s API) Metrics:**
```promql
# Stream connections
nginx_stream_connections{instance=~"nginx-lb.*"}

# Stream upstream status
nginx_stream_upstream_up{instance=~"nginx-lb.*",upstream="k8s_api_servers"}
```

### 2. System Metrics (Node Exporter)

**CPU:**
```promql
# CPU usage
100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle",instance=~"nginx-lb.*"}[5m])) * 100)

# Load average
node_load1{instance=~"nginx-lb.*"}
node_load5{instance=~"nginx-lb.*"}
node_load15{instance=~"nginx-lb.*"}
```

**Memory:**
```promql
# Memory usage percentage
100 - ((node_memory_MemAvailable_bytes{instance=~"nginx-lb.*"} / node_memory_MemTotal_bytes{instance=~"nginx-lb.*"}) * 100)

# Available memory
node_memory_MemAvailable_bytes{instance=~"nginx-lb.*"}
```

**Disk:**
```promql
# Disk usage percentage
100 - ((node_filesystem_avail_bytes{instance=~"nginx-lb.*",mountpoint="/"} / node_filesystem_size_bytes{instance=~"nginx-lb.*",mountpoint="/"}) * 100)

# Disk I/O
rate(node_disk_read_bytes_total{instance=~"nginx-lb.*"}[5m])
rate(node_disk_written_bytes_total{instance=~"nginx-lb.*"}[5m])
```

**Network:**
```promql
# Network throughput
rate(node_network_receive_bytes_total{instance=~"nginx-lb.*",device!~"lo|docker.*|veth.*"}[5m])
rate(node_network_transmit_bytes_total{instance=~"nginx-lb.*",device!~"lo|docker.*|veth.*"}[5m])

# Network errors
rate(node_network_receive_errs_total{instance=~"nginx-lb.*"}[5m])
rate(node_network_transmit_errs_total{instance=~"nginx-lb.*"}[5m])
```

### 3. Cluster Metrics (Custom Exporters)

**Corosync Cluster Status:**
```promql
# Cluster members online
corosync_members_online{cluster="nginx-lb-cluster"}

# Cluster quorum status (1 = quorate, 0 = not quorate)
corosync_quorum_status{cluster="nginx-lb-cluster"}

# Ring status (1 = healthy, 0 = unhealthy)
corosync_ring_status{cluster="nginx-lb-cluster",ring_id="0"}
```

**Pacemaker Resource Status:**
```promql
# VIP resource status (1 = running, 0 = stopped)
pacemaker_resource_status{resource="cluster-vip",cluster="nginx-lb-cluster"}

# VIP resource location (which node)
pacemaker_resource_location{resource="cluster-vip",cluster="nginx-lb-cluster"}

# Cluster failover events
rate(pacemaker_failover_total{cluster="nginx-lb-cluster"}[5m])
```

**VIP Availability:**
```promql
# VIP probe success (via Blackbox Exporter)
probe_success{target="192.168.10.250"}

# VIP response time
probe_duration_seconds{target="192.168.10.250"}

# K8s API availability through VIP
probe_http_status_code{target="https://192.168.10.250:6443"}
```

## Exporters Deployment

### 1. Nginx Prometheus Exporter

**Deployment Method:** Run as systemd service on each nginx-lb node

**Installation:**
```bash
# On each nginx-lb node
sudo wget -O /usr/local/bin/nginx-prometheus-exporter https://github.com/nginxinc/nginx-prometheus-exporter/releases/download/v0.11.0/nginx-prometheus-exporter_0.11.0_linux_amd64.tar.gz
sudo chmod +x /usr/local/bin/nginx-prometheus-exporter

# Create systemd service
sudo tee /etc/systemd/system/nginx-exporter.service <<EOF
[Unit]
Description=Nginx Prometheus Exporter
After=network.target nginx.service

[Service]
Type=simple
User=nobody
ExecStart=/usr/local/bin/nginx-prometheus-exporter -nginx.scrape-uri=http://localhost:8888/stub_status
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable nginx-exporter
sudo systemctl start nginx-exporter
```

**Configuration in nginx:**
```nginx
# Add to nginx configuration (already present)
server {
    listen 8888;
    location /stub_status {
        stub_status on;
        access_log off;
        allow 127.0.0.1;
        deny all;
    }
}
```

**Prometheus Scrape Config:**
```yaml
- job_name: 'nginx-lb'
  static_configs:
    - targets:
        - '192.168.10.251:9113'  # nginx-lb01
        - '192.168.10.252:9113'  # nginx-lb02
      labels:
        cluster: 'nginx-lb-cluster'
        service: 'load-balancer'
```

### 2. Node Exporter

**Deployment Method:** Run as systemd service on each nginx-lb node

**Installation:**
```bash
# On each nginx-lb node
sudo wget -O - https://github.com/prometheus/node_exporter/releases/download/v1.7.0/node_exporter-1.7.0.linux-amd64.tar.gz | tar xz
sudo mv node_exporter-1.7.0.linux-amd64/node_exporter /usr/local/bin/
sudo rm -rf node_exporter-1.7.0.linux-amd64

# Create systemd service
sudo tee /etc/systemd/system/node-exporter.service <<EOF
[Unit]
Description=Node Exporter
After=network.target

[Service]
Type=simple
User=nobody
ExecStart=/usr/local/bin/node_exporter
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable node-exporter
sudo systemctl start node-exporter
```

**Prometheus Scrape Config:**
```yaml
- job_name: 'node-nginx-lb'
  static_configs:
    - targets:
        - '192.168.10.251:9100'  # nginx-lb01
        - '192.168.10.252:9100'  # nginx-lb02
      labels:
        cluster: 'nginx-lb-cluster'
```

### 3. Custom Cluster Status Exporter

**Deployment Method:** Python script with Flask, run as systemd service

**Script Location:** `/usr/local/bin/cluster-status-exporter.py`

```python
#!/usr/bin/env python3
import subprocess
import time
from flask import Flask, Response
from prometheus_client import Gauge, generate_latest, REGISTRY

app = Flask(__name__)

# Define metrics
cluster_members_online = Gauge('corosync_members_online', 'Number of online cluster members', ['cluster'])
cluster_quorum_status = Gauge('corosync_quorum_status', 'Cluster quorum status (1=quorate, 0=not)', ['cluster'])
pacemaker_resource_status = Gauge('pacemaker_resource_status', 'Resource status (1=running, 0=stopped)', ['resource', 'cluster'])
pacemaker_resource_on_node = Gauge('pacemaker_resource_on_node', 'Which node resource is on (1=this_node, 0=other)', ['resource', 'node', 'cluster'])

CLUSTER_NAME = 'nginx-lb-cluster'

def get_cluster_status():
    """Get corosync cluster status"""
    try:
        result = subprocess.run(['crm', 'status'], capture_output=True, text=True, timeout=5)
        return result.stdout
    except Exception as e:
        print(f"Error getting cluster status: {e}")
        return ""

def parse_cluster_metrics():
    """Parse cluster status and update metrics"""
    status = get_cluster_status()

    # Count online nodes
    online_count = status.count('Online:')
    if 'nginx-lb01' in status and 'nginx-lb02' in status:
        online_count = 2
    elif 'nginx-lb01' in status or 'nginx-lb02' in status:
        online_count = 1
    else:
        online_count = 0

    cluster_members_online.labels(cluster=CLUSTER_NAME).set(online_count)

    # Check quorum
    if 'partition with quorum' in status.lower():
        cluster_quorum_status.labels(cluster=CLUSTER_NAME).set(1)
    else:
        cluster_quorum_status.labels(cluster=CLUSTER_NAME).set(0)

    # Check VIP resource status
    if 'cluster-vip' in status and 'Started' in status:
        pacemaker_resource_status.labels(resource='cluster-vip', cluster=CLUSTER_NAME).set(1)
    else:
        pacemaker_resource_status.labels(resource='cluster-vip', cluster=CLUSTER_NAME).set(0)

    # Check which node has VIP
    import socket
    hostname = socket.gethostname()
    if hostname in status and 'cluster-vip' in status:
        pacemaker_resource_on_node.labels(resource='cluster-vip', node=hostname, cluster=CLUSTER_NAME).set(1)
    else:
        pacemaker_resource_on_node.labels(resource='cluster-vip', node=hostname, cluster=CLUSTER_NAME).set(0)

@app.route('/metrics')
def metrics():
    parse_cluster_metrics()
    return Response(generate_latest(REGISTRY), mimetype='text/plain')

@app.route('/health')
def health():
    return "OK"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9200)
```

**Systemd Service:**
```bash
sudo tee /etc/systemd/system/cluster-status-exporter.service <<EOF
[Unit]
Description=Cluster Status Exporter
After=network.target pacemaker.service

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /usr/local/bin/cluster-status-exporter.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable cluster-status-exporter
sudo systemctl start cluster-status-exporter
```

**Prometheus Scrape Config:**
```yaml
- job_name: 'cluster-status-nginx-lb'
  static_configs:
    - targets:
        - '192.168.10.251:9200'  # nginx-lb01
        - '192.168.10.252:9200'  # nginx-lb02
      labels:
        cluster: 'nginx-lb-cluster'
```

### 4. Blackbox Exporter (VIP Probing)

**Deployment Method:** Deploy in Kubernetes cluster

**Helm Chart:**
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install blackbox-exporter prometheus-community/prometheus-blackbox-exporter \
  --namespace prometheus \
  --create-namespace
```

**Prometheus Scrape Config:**
```yaml
- job_name: 'blackbox-vip-probe'
  metrics_path: /probe
  params:
    module: [icmp]
  static_configs:
    - targets:
        - 192.168.10.250  # VIP
  relabel_configs:
    - source_labels: [__address__]
      target_label: __param_target
    - source_labels: [__param_target]
      target_label: instance
    - target_label: __address__
      replacement: blackbox-exporter.prometheus.svc.cluster.local:9115

- job_name: 'blackbox-k8s-api-probe'
  metrics_path: /probe
  params:
    module: [http_2xx]
  static_configs:
    - targets:
        - https://192.168.10.250:6443  # K8s API through VIP
  relabel_configs:
    - source_labels: [__address__]
      target_label: __param_target
    - source_labels: [__param_target]
      target_label: instance
    - target_label: __address__
      replacement: blackbox-exporter.prometheus.svc.cluster.local:9115
```

## Alerting Rules

Create alert rules in Prometheus AlertManager configuration.

**File:** `k8s/prometheus/alerts/nginx-lb-alerts.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-lb-alerts
  namespace: prometheus
data:
  nginx-lb-alerts.yml: |
    groups:
      - name: nginx-lb-critical
        interval: 30s
        rules:
          # VIP not responding
          - alert: NginxLBVIPDown
            expr: probe_success{target="192.168.10.250"} == 0
            for: 1m
            labels:
              severity: critical
              component: nginx-lb
            annotations:
              summary: "Nginx LB VIP is not responding"
              description: "The nginx load balancer VIP (192.168.10.250) has been unreachable for more than 1 minute. This is a CRITICAL issue affecting all cluster access."

          # Node down
          - alert: NginxLBNodeDown
            expr: up{job="nginx-lb"} == 0
            for: 2m
            labels:
              severity: critical
              component: nginx-lb
            annotations:
              summary: "Nginx LB node {{ $labels.instance }} is down"
              description: "Nginx load balancer node {{ $labels.instance }} has been down for more than 2 minutes. Cluster is operating in degraded mode."

          # Both nodes down (extremely critical)
          - alert: NginxLBClusterDown
            expr: count(up{job="nginx-lb"} == 0) == 2
            for: 1m
            labels:
              severity: critical
              component: nginx-lb
            annotations:
              summary: "Nginx LB cluster is completely down"
              description: "BOTH nginx load balancer nodes are down. Kubernetes API and NodePort services are UNAVAILABLE. IMMEDIATE ACTION REQUIRED."

          # K8s API not accessible through VIP
          - alert: KubernetesAPIVIPUnreachable
            expr: probe_success{target="https://192.168.10.250:6443"} == 0
            for: 2m
            labels:
              severity: critical
              component: nginx-lb
            annotations:
              summary: "Kubernetes API not accessible through VIP"
              description: "The Kubernetes API server is not accessible through the load balancer VIP. kubectl operations will fail."

          # Cluster not quorate
          - alert: NginxLBClusterNoQuorum
            expr: corosync_quorum_status{cluster="nginx-lb-cluster"} == 0
            for: 1m
            labels:
              severity: critical
              component: nginx-lb
            annotations:
              summary: "Nginx LB cluster has lost quorum"
              description: "The nginx LB cluster does not have quorum. Failover may not work correctly."

          # VIP resource not running
          - alert: NginxLBVIPResourceStopped
            expr: pacemaker_resource_status{resource="cluster-vip"} == 0
            for: 1m
            labels:
              severity: critical
              component: nginx-lb
            annotations:
              summary: "Nginx LB VIP resource is not running"
              description: "The cluster-vip resource is stopped in Pacemaker. VIP may not be accessible."

      - name: nginx-lb-warning
        interval: 1m
        rules:
          # Single node down
          - alert: NginxLBSingleNodeDown
            expr: count(up{job="nginx-lb"} == 0) == 1
            for: 5m
            labels:
              severity: warning
              component: nginx-lb
            annotations:
              summary: "One nginx LB node is down"
              description: "One nginx load balancer node has been down for 5 minutes. Cluster is operating with no redundancy."

          # High error rate
          - alert: NginxLBHighErrorRate
            expr: rate(nginx_http_requests_total{status=~"5.."}[5m]) > 5
            for: 5m
            labels:
              severity: warning
              component: nginx-lb
            annotations:
              summary: "High 5xx error rate on nginx LB"
              description: "Nginx load balancer is returning high rate of 5xx errors. Check backend health."

          # Backend node down
          - alert: NginxLBBackendDown
            expr: nginx_upstream_up == 0
            for: 3m
            labels:
              severity: warning
              component: nginx-lb
            annotations:
              summary: "Nginx LB backend {{ $labels.backend }} is down"
              description: "Backend {{ $labels.backend }} in upstream {{ $labels.upstream }} has been down for 3 minutes."

          # Failover event
          - alert: NginxLBFailoverOccurred
            expr: changes(pacemaker_resource_location{resource="cluster-vip"}[5m]) > 0
            labels:
              severity: warning
              component: nginx-lb
            annotations:
              summary: "Nginx LB VIP has failed over"
              description: "The VIP has moved to a different node. Investigate why the primary failed."

          # High CPU usage
          - alert: NginxLBHighCPU
            expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle",instance=~"nginx-lb.*"}[5m])) * 100) > 80
            for: 10m
            labels:
              severity: warning
              component: nginx-lb
            annotations:
              summary: "High CPU usage on {{ $labels.instance }}"
              description: "CPU usage on {{ $labels.instance }} has been above 80% for 10 minutes."

          # High memory usage
          - alert: NginxLBHighMemory
            expr: 100 - ((node_memory_MemAvailable_bytes{instance=~"nginx-lb.*"} / node_memory_MemTotal_bytes{instance=~"nginx-lb.*"}) * 100) > 80
            for: 10m
            labels:
              severity: warning
              component: nginx-lb
            annotations:
              summary: "High memory usage on {{ $labels.instance }}"
              description: "Memory usage on {{ $labels.instance }} has been above 80% for 10 minutes."

          # High disk usage
          - alert: NginxLBHighDisk
            expr: 100 - ((node_filesystem_avail_bytes{instance=~"nginx-lb.*",mountpoint="/"} / node_filesystem_size_bytes{instance=~"nginx-lb.*",mountpoint="/"}) * 100) > 80
            for: 10m
            labels:
              severity: warning
              component: nginx-lb
            annotations:
              summary: "High disk usage on {{ $labels.instance }}"
              description: "Disk usage on {{ $labels.instance }} has been above 80% for 10 minutes."

          # Many active connections
          - alert: NginxLBHighConnectionCount
            expr: nginx_connections_active > 500
            for: 10m
            labels:
              severity: warning
              component: nginx-lb
            annotations:
              summary: "High connection count on {{ $labels.instance }}"
              description: "Active connection count on {{ $labels.instance }} has been above 500 for 10 minutes."
```

## Grafana Dashboards

### 1. Nginx Load Balancer Overview Dashboard

**Dashboard JSON:** `k8s/prometheus/dashboards/nginx-lb-overview.json`

**Panels:**
1. **Cluster Status**
   - VIP status (up/down)
   - Nodes online count
   - Quorum status
   - Active node (which has VIP)

2. **Service Health**
   - Nginx service status (both nodes)
   - Corosync status
   - Pacemaker status
   - Last failover time

3. **Traffic Overview**
   - Total requests/second
   - Requests by status code (2xx, 4xx, 5xx)
   - Active connections
   - Request latency (p50, p95, p99)

4. **Backend Health**
   - K8s API servers status
   - Worker nodes status
   - Backend response times
   - Failed health checks

5. **System Resources**
   - CPU usage (both nodes)
   - Memory usage (both nodes)
   - Disk usage (both nodes)
   - Network throughput

6. **Recent Events**
   - Failover events
   - Backend failures
   - Error rate spikes
   - Configuration reloads

### 2. Nginx Load Balancer Detailed Dashboard

**Panels:**
1. **Connection Metrics**
   - Connections by state (active, reading, writing, waiting)
   - Connection rate
   - Connection handling rate
   - Dropped connections

2. **Upstream Performance**
   - Per-backend request rate
   - Per-backend response time
   - Per-backend error rate
   - Backend health status

3. **Stream (K8s API) Metrics**
   - Stream connections
   - Stream bytes sent/received
   - Stream upstream status

4. **HTTP (NodePort) Metrics**
   - HTTP requests by service (ArgoCD, Traefik)
   - HTTP status codes distribution
   - Request size distribution
   - Response size distribution

5. **Error Analysis**
   - Error rate over time
   - Error types
   - Failed backends
   - Timeout events

6. **Performance Metrics**
   - Request processing time
   - Upstream response time
   - Queue depth
   - Worker utilization

### Dashboard Import

```bash
# Create ConfigMap with dashboard JSON
kubectl create configmap nginx-lb-dashboard \
  --from-file=nginx-lb-overview.json \
  --namespace prometheus

# Add label for Grafana sidecar to pick up
kubectl label configmap nginx-lb-dashboard \
  grafana_dashboard=1 \
  --namespace prometheus
```

## Implementation Steps

### Phase 1: Basic Monitoring (Week 1)

1. **Deploy Node Exporter**
   - Install on both nginx-lb nodes
   - Configure Prometheus scrape targets
   - Verify metrics collection

2. **Deploy Nginx Exporter**
   - Install on both nginx-lb nodes
   - Configure stub_status in nginx
   - Configure Prometheus scrape targets
   - Verify metrics collection

3. **Configure Basic Alerts**
   - Node down alerts
   - VIP down alerts
   - High error rate alerts

4. **Create Basic Dashboard**
   - Cluster status panel
   - Service health panel
   - Traffic overview panel

### Phase 2: Advanced Monitoring (Week 2)

1. **Deploy Custom Cluster Status Exporter**
   - Install Python script on both nodes
   - Configure as systemd service
   - Configure Prometheus scrape targets
   - Verify cluster metrics

2. **Deploy Blackbox Exporter**
   - Install in Kubernetes cluster
   - Configure VIP probing
   - Configure K8s API probing
   - Verify probes working

3. **Configure Advanced Alerts**
   - Failover event alerts
   - Backend health alerts
   - Resource usage alerts
   - Performance alerts

4. **Create Detailed Dashboard**
   - Upstream performance panels
   - Error analysis panels
   - Resource usage panels

### Phase 3: Integration and Tuning (Week 3)

1. **Alert Routing Configuration**
   - Configure alert channels (email, Slack)
   - Set up on-call rotation
   - Test alert delivery

2. **Dashboard Refinement**
   - Add annotations for events
   - Create dashboard variables
   - Set up auto-refresh
   - Share with team

3. **Documentation**
   - Document all metrics
   - Document alert thresholds
   - Create runbook for alerts
   - Train team on dashboards

4. **Testing**
   - Trigger test alerts
   - Verify dashboard accuracy
   - Test during failover
   - Validate alert timing

## Maintenance

### Regular Tasks

**Daily:**
- Review dashboard for anomalies
- Check for active alerts
- Verify all exporters running

**Weekly:**
- Review alert history
- Adjust alert thresholds if needed
- Check for new metrics to track

**Monthly:**
- Review dashboard layouts
- Update documentation
- Audit alert rules
- Clean up old metrics

### Troubleshooting

**No Metrics Appearing:**
1. Check exporter service status
2. Verify network connectivity
3. Check Prometheus scrape targets
4. Review Prometheus logs

**Incorrect Metrics:**
1. Verify exporter configuration
2. Check nginx stub_status output
3. Review cluster status command output
4. Test metrics endpoint manually

**Missing Alerts:**
1. Check alert rule syntax
2. Verify AlertManager configuration
3. Check alert channel configuration
4. Review AlertManager logs

## References

- [Nginx Prometheus Exporter](https://github.com/nginxinc/nginx-prometheus-exporter)
- [Node Exporter](https://github.com/prometheus/node_exporter)
- [Blackbox Exporter](https://github.com/prometheus/blackbox_exporter)
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Dashboard Guide](https://grafana.com/docs/grafana/latest/dashboards/)

---

**Document Version:** 1.0
**Last Updated:** 2025-11-06
**Next Review:** Quarterly
