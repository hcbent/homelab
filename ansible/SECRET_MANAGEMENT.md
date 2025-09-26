# Secret Management with Ansible Vault

This document explains how to manage secrets securely in this Ansible setup.

## Overview

We use Ansible Vault to encrypt sensitive data like passwords, API keys, and SSH private keys. The vault password is stored in `.vault_pass` and configured in `ansible.cfg`.

## Directory Structure

```
group_vars/all/
├── main.yml        # Non-sensitive global variables
└── vault.yml       # Encrypted secrets (global)

host_vars/HOST/
├── main.yml        # Non-sensitive host variables
└── vault.yml       # Encrypted secrets (host-specific)
```

## Using Secrets in Playbooks

Secrets are accessible via the `secrets` variable:

```yaml
- name: Configure application
  template:
    src: app.conf.j2
    dest: /etc/app/config
  vars:
    api_key: "{{ secrets.apps.radarr_api_key }}"
    db_password: "{{ secrets.databases.mysql_root_password }}"
```

## Common Commands

### Editing Encrypted Files
```bash
# Edit global secrets
ansible-vault edit group_vars/all/vault.yml

# Edit host-specific secrets
ansible-vault edit host_vars/lidarr/vault.yml
```

### Encrypting/Decrypting Files
```bash
# Encrypt a file
ansible-vault encrypt group_vars/all/vault.yml

# Decrypt a file (for editing manually)
ansible-vault decrypt group_vars/all/vault.yml
# Remember to encrypt again after editing!
ansible-vault encrypt group_vars/all/vault.yml
```

### Running Playbooks
Playbooks automatically use the vault password from `.vault_pass`:

```bash
# Normal playbook run - vault is handled automatically
ansible-playbook -i inventory/home playbooks/setup_host.yml
```

### Encrypting Individual Strings
```bash
# Encrypt a single value
ansible-vault encrypt_string 'mysecretpassword' --name 'db_password'
```

## Adding New Secrets

1. **For global secrets**: Edit `group_vars/all/vault.yml`
2. **For host-specific secrets**: Create/edit `host_vars/HOST/vault.yml`

### Example: Adding a new application secret

```bash
ansible-vault edit group_vars/all/vault.yml
```

Add to the `apps` section:
```yaml
vault_secrets:
  apps:
    new_app_api_key: "your_secret_key_here"
```

## Security Best Practices

1. **Never commit unencrypted secrets** - Use `.gitignore` to prevent accidents
2. **Store vault password securely** - Keep `.vault_pass` in your password manager
3. **Use host-specific vaults** for secrets that vary by host
4. **Rotate secrets regularly** and update vault files
5. **Backup vault password** - You cannot decrypt without it!

## Vault Password Management

The vault password is stored in `.vault_pass` (gitignored). To recreate:

```bash
# Generate new vault password
openssl rand -base64 32 > .vault_pass
chmod 600 .vault_pass

# You'll need to re-encrypt all vault files with the new password
ansible-vault rekey group_vars/all/vault.yml
ansible-vault rekey host_vars/*/vault.yml
```

## Troubleshooting

### "Vault password file not found"
Ensure `.vault_pass` exists and has correct permissions:
```bash
ls -la .vault_pass
# Should show: -rw------- 1 user user
```

### "Decryption failed"
The vault password is incorrect. Check your `.vault_pass` file.

### "Variable is undefined"
Ensure the variable path exists in your vault file structure and the vault file is included in your playbook scope.

## Available Secrets

Current secrets structure:

### Global Secrets (`group_vars/all/vault.yml`)
- `secrets.proxmox.api_password` - Proxmox API password
- `secrets.apps.plex_claim_token` - Plex claim token
- `secrets.apps.radarr_api_key` - Radarr API key
- `secrets.apps.sonarr_api_key` - Sonarr API key
- `secrets.apps.lidarr_api_key` - Lidarr API key
- `secrets.monitoring.grafana_admin_password` - Grafana admin password
- `secrets.auth.ssh_private_key` - SSH private key for deployments

### Host Secrets (`host_vars/HOST/vault.yml`)
- `host_secrets.HOST.api_key` - Host-specific API keys
- `host_secrets.local_db.*` - Host-specific database credentials