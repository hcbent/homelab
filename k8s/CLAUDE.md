- Address pods using the nginx-lb instead of directly whenever possible
- NEVER modify PVC configurations or Helm values that affect persistent storage without explicitly warning about potential data loss and getting confirmation
- Before making ArgoCD/Helm changes, always check what's currently deployed with `kubectl get` commands
- ArgoCD apps with `prune: true` will DELETE resources that disappear from manifests - be extremely careful

## Mealie Upgrades
Mealie uses Alembic database migrations that are tightly coupled to specific app versions:
- NEVER upgrade mealie image without checking release notes for migration compatibility
- The `nightly` tag is required because stable releases may lag behind database schema
- Before upgrading: back up both `mealie-data` and `mealie-postgres` PVCs
- Check current DB migration: `kubectl exec -n home-apps deploy/mealie-postgres -- psql -U mealie -d mealie -c "SELECT * FROM alembic_version;"`
- If mealie fails with "No such revision", the image version doesn't match the database schema
