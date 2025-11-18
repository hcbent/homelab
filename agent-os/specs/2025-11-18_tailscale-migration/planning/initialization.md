# Spec Initialization: Tailscale Migration

**Date:** 2025-11-18
**Spec Name:** tailscale-migration

## Raw Idea

Migrate homelab infrastructure from Cloudflare DNS + NGINX Proxy Manager architecture to Tailscale-based zero-trust mesh networking while maintaining public access for two specific services (Kibana and CCHS Makerspace) via Tailscale Funnel.

## Key Requirements

1. Deploy Tailscale on Kubernetes cluster (km01, km02, km03)
2. Configure private access to all homelab services via Tailscale VPN mesh
3. Set up Tailscale Funnel for two public services:
   - kibana.bwortman.us
   - cchs.makerspace.hcbent.com
4. Deploy internal NGINX for clean URLs (replacing NGINX Proxy Manager)
5. Configure MagicDNS for service discovery
6. Enable on-demand Funnel for very infrequent service sharing (single user at a time)
7. Integrate with existing Vault for Tailscale auth keys
8. Decommission old NGINX Proxy Manager and Cloudflare configuration

## Existing Infrastructure

- Kubernetes cluster (3 nodes: km01, km02, km03)
- Helm for package management
- Ansible for configuration management
- Terraform for infrastructure as code
- Vault for secrets management
- Services: Sonarr, Radarr, qBittorrent, Actual Budget, Kibana, CCHS Makerspace app, and others

## User Preferences

- Deploy new Kubernetes services as NodePort
- NFS share called "tank"
- Store secrets in Vault
- Use /Users/bret/.ssh/github_rsa for SSH operations

## Context

This is a comprehensive networking transformation to implement enterprise-grade zero-trust security at homelab scale, reducing attack surface while improving manageability and user experience.
