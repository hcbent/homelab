# Vault Policy for Democratic CSI
# This policy allows democratic-csi to read FreeNAS credentials
path "secret/data/homelab/freenas/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/homelab/freenas/*" {
  capabilities = ["read", "list"]
}

# Vault Policy for Elasticsearch
# Allows reading Elasticsearch passwords
path "secret/data/homelab/elasticsearch/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/homelab/elasticsearch/*" {
  capabilities = ["read", "list"]
}

# Vault Policy for Media Apps (Plex, Radarr, Sonarr, etc.)
path "secret/data/homelab/apps/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/homelab/apps/*" {
  capabilities = ["read", "list"]
}

# Vault Policy for Home Automation
path "secret/data/homelab/home-assistant/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/homelab/home-assistant/*" {
  capabilities = ["read", "list"]
}

# Admin policy for managing secrets
path "secret/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "sys/mounts/*" {
  capabilities = ["read", "list"]
}
