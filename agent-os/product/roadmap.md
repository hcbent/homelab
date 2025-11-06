# Product Roadmap

1. [x] Kubespray K8s Cluster Deployment — Implement automated Kubernetes cluster deployment using kubespray (~/git/kubespray) as an alternative to K3s setup. Create inventory configuration, customize cluster parameters, and document deployment procedures. Enable production-grade cluster features and integration with existing Proxmox/Ansible infrastructure. `L`

2. [x] Nginx Load Balancer for K8s API — Deploy dedicated HA load balancer cluster for Kubernetes API server high availability. Create Terraform module for nginx-lb VM provisioning, implement Ansible playbook for nginx configuration with Corosync/Pacemaker failover targeting all control plane nodes, configure VIP (192.168.10.250), and update kubeconfig and certificates to use load balancer endpoint instead of direct node access. `M`

3. [ ] Docker Compose to ArgoCD Migration — Convert existing docker-compose deployments to ArgoCD Application manifests. Identify all docker-compose files under docker/ directory, create corresponding Helm charts or Kubernetes manifests, configure ArgoCD apps with proper sync policies, and migrate persistent data to CSI-backed volumes. Document migration procedures and rollback steps. `L`

4. [ ] Storage Backend Hardening — Implement Democratic CSI health monitoring, automated failover testing, and snapshot policies for all persistent volumes. Add documentation for backup/restore procedures and disaster recovery testing. `M`

5. [ ] Vault High Availability — Deploy multi-node Vault cluster with Raft storage backend, configure auto-unseal using cloud KMS or transit encryption, and implement automated backup workflows with off-site replication. `L`

6. [ ] Monitoring & Alerting Enhancement — Expand Prometheus metrics collection to all infrastructure components (Proxmox, TrueNAS, Vault), create comprehensive Grafana dashboards for cluster health, and configure AlertManager with notification channels (email, Slack, PagerDuty). `M`

7. [ ] Kubernetes Security Hardening — Implement network policies for pod-to-pod communication, configure pod security standards (restricted mode), enable RBAC with least-privilege service accounts, and integrate external-secrets operator for Vault secret injection. `L`

8. [ ] Certificate Management Automation — Replace step-certificates with cert-manager and Let's Encrypt for external-facing services, automate internal CA certificate rotation, and implement certificate monitoring with expiration alerts. `M`

9. [ ] Infrastructure Testing Framework — Create automated testing suite using Terraform validate, tfsec for security scanning, Ansible Molecule for playbook testing, and K8s validation via kubeval/kube-score. Add pre-commit hooks for all validation checks. `L`

10. [ ] Disaster Recovery Automation — Build complete disaster recovery playbooks including Vault recovery procedures, Kubernetes cluster rebuild from etcd backups, and data restoration from TrueNAS snapshots. Create quarterly DR testing schedule and runbooks. `XL`

11. [ ] Observability Platform Consolidation — Integrate Elasticsearch logs with Prometheus metrics in unified Grafana dashboards, implement distributed tracing with Jaeger or Tempo, and create service-level objective (SLO) monitoring for critical applications. `L`

12. [ ] Application Lifecycle Management — Implement blue-green deployment strategies for critical services, add automated health checks and rollback capabilities in ArgoCD, and create staging/production environment separation within the cluster. `M`

13. [ ] Cost & Resource Optimization — Build resource usage dashboards showing CPU/memory/storage consumption per application, implement horizontal pod autoscaling for appropriate workloads, and create capacity planning reports with growth projections. `M`

14. [ ] Multi-Cluster Management — Add support for deploying secondary Kubernetes clusters (edge, development, production), implement cluster federation, and create centralized management plane for multi-cluster observability and policy enforcement. `XL`

15. [ ] Backup & Replication Strategy — Implement Velero for Kubernetes application backups, configure automated TrueNAS replication to secondary storage, integrate Elasticsearch snapshot repository, and create backup validation testing framework. `L`

16. [ ] GitOps Workflow Enhancement — Expand ArgoCD usage to infrastructure layer (progressive delivery for Ansible changes), implement application sets for multi-environment deployments, and add automatic PR creation for dependency updates via Renovate. `M`

17. [ ] Service Mesh Integration — Deploy Istio or Linkerd for advanced traffic management, implement mutual TLS between services, add circuit breaking and retry policies, and create service mesh observability dashboards. `XL`

18. [ ] Infrastructure Documentation Portal — Build automated documentation generation from Terraform/Ansible code, create interactive network diagrams showing service dependencies, and implement runbook automation with searchable incident response procedures. `M`

> Notes
> - Order items by technical dependencies and infrastructure maturity model
> - Each item represents an end-to-end functional and testable enhancement
> - Prioritizes security, reliability, and operational excellence
> - Earlier items establish foundation for later advanced features
> - Focus on production-grade capabilities while maintaining homelab accessibility
