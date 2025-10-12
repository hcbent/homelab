# Cerebro - Elasticsearch Monitoring

Cerebro is a web admin tool for Elasticsearch that provides cluster monitoring, index management, and query execution capabilities.

## Quick Start

```bash
# Start Cerebro
docker-compose up -d

# View logs
docker-compose logs -f cerebro

# Stop Cerebro
docker-compose down
```

## Access

Once running, access Cerebro at: http://localhost:9000

The Cerebro home page will show pre-configured clusters from `application.conf` - simply click on a cluster to connect to it.

## Quick Connection to K8s Elasticsearch

To connect to your Kubernetes Elasticsearch cluster:

1. Port-forward the Elasticsearch service:
   ```bash
   kubectl port-forward -n elastic-stack svc/elasticsearch 9200:9200
   ```

2. Start Cerebro:
   ```bash
   docker-compose up -d
   ```

3. Open http://localhost:9000 and click on "K8s Elasticsearch (via port-forward)"

## Configuration

### Connecting to Elasticsearch

Edit `cerebro/config/application.conf` to configure your Elasticsearch connections:

#### For Kubernetes Elasticsearch Cluster

If connecting to your K8s Elasticsearch cluster, you have a few options:

1. **Port Forward to Elasticsearch** (recommended for testing):
   ```bash
   kubectl port-forward -n elastic-stack svc/elasticsearch 9200:9200
   ```
   Then use `http://host.docker.internal:9200` in the Cerebro config.

2. **Direct Connection** (if accessible from Docker host):
   ```
   hosts = [
     {
       host = "http://es-master.elastic-stack.svc.cluster.local:9200"
       name = "K8s Elasticsearch"
     }
   ]
   ```

3. **Use External IP/LoadBalancer** (if configured):
   ```
   hosts = [
     {
       host = "http://<elasticsearch-external-ip>:9200"
       name = "K8s Elasticsearch"
     }
   ]
   ```

### Authentication

If your Elasticsearch cluster requires authentication, uncomment and configure the auth section in `application.conf`:

```
hosts = [
  {
    host = "http://elasticsearch:9200"
    name = "Production Cluster"
    auth = {
      username = "elastic"
      password = "your-password"
    }
  }
]
```

### Securing Cerebro

To add authentication to Cerebro itself, uncomment the auth section in `application.conf`:

```
auth = {
  type: basic
  settings: {
    username = "admin"
    password = "admin123"
  }
}
```

## Features

- Real-time cluster monitoring
- Index management (create, delete, optimize)
- Snapshot management
- Query execution via REST API
- Template management
- Node statistics and metrics
- Shard allocation visualization

## Directory Structure

```
elastic/
├── docker-compose.yml           # Docker Compose configuration
├── README.md                    # This file
└── cerebro/
    ├── config/
    │   └── application.conf     # Cerebro configuration
    └── logs/                    # Application logs
```

## Troubleshooting

### Cannot connect to Elasticsearch

1. Verify Elasticsearch is accessible from the Docker container
2. Check firewall rules
3. Verify authentication credentials if required
4. Check Cerebro logs: `docker-compose logs cerebro`

### Port already in use

If port 9000 is already in use, modify the port mapping in `docker-compose.yml`:
```yaml
ports:
  - "9001:9000"  # Use 9001 instead
```

## References

- [Cerebro GitHub](https://github.com/lmenezes/cerebro)
- [Elasticsearch Documentation](https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html)
