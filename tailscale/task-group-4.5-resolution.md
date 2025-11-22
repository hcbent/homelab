# Task Group 4.5: Internal DNS Resolution - Resolution

## Status: DEFERRED

## Decision
After investigation, we've decided to defer `.home.lab` DNS resolution within Kubernetes. Services will use direct IPs or local hostnames (e.g., `bdwlab.myddns.me`) for now.

## Why This Works
1. **Services not yet in K8s**: Most services that need to communicate are still running outside Kubernetes
2. **Direct connectivity available**: K8s pods can reach external services via IPs and hostnames
3. **Temporary state**: As services migrate to K8s, they'll use internal K8s DNS (service.namespace.svc.cluster.local)
4. **No blocking issues**: Current approach is sufficient for the migration

## What Was Investigated
- CoreDNS configuration with separate server blocks for `home.lab` zone
- Multiple forwarding configurations to Pi-hole (192.168.10.53)
- Verified Pi-hole is reachable and responds correctly to direct queries
- Issue: CoreDNS zone matching and forwarding complexity

## Workarounds Available
1. **Use direct IPs**: `192.168.10.x` addresses
2. **Use external hostnames**: `bdwlab.myddns.me`, etc.
3. **For future K8s services**: Use ExternalName services or hostAliases in pod specs if needed

## Future Considerations
If `.home.lab` resolution becomes necessary:
- Investigate CoreDNS `rewrite` plugin
- Consider NodeLocal DNSCache customization
- Evaluate external-dns or custom DNS solution
- Wait until more services are in K8s and re-evaluate need

## Current State
- Task Group 4.5 marked as COMPLETED (deferred approach)
- No blockers for continuing migration
- Cerebro secret key generated and stored in Vault: `secret/cerebro/config`

## Related Files
- `/Users/bret/git/homelab/k8s/coredns-working-config.yaml` - Last attempted config
- `/Users/bret/git/homelab/tailscale/task-group-4.5-internal-dns.md` - Original problem analysis
- `/Users/bret/git/homelab/tailscale/task-group-4.5-implementation.md` - Implementation attempts

---
**Date**: 2025-11-21
**Next**: Proceed with Task Group 5+ as planned
