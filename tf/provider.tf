provider "proxmox" {
    pm_api_url = var.pm_api_url
    pm_user = coalesce(var.pm_user, try(data.vault_kv_secret_v2.proxmox_credentials.data["username"], ""))
    pm_password = coalesce(var.pm_password, try(data.vault_kv_secret_v2.proxmox_credentials.data["password"], ""))
    pm_tls_insecure = var.pm_tls_insecure
}

