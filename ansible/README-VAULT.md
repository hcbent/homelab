# Using HashiCorp Vault with Ansible

This guide explains how to integrate Ansible with your standalone Vault server for secret management.

## Prerequisites

1. **Vault server running** at `https://vault.lab.thewortmans.org:8200`
2. **Vault initialized** and unsealed
3. **Python hvac library** installed: `pip install hvac`
4. **Ansible Vault plugin** (optional): `ansible-galaxy collection install community.hashi_vault`

## Authentication Methods

### Method 1: Using Vault Token (Simple)

```bash
# Export your Vault token
export VAULT_ADDR=https://vault.lab.thewortmans.org:8200
export VAULT_TOKEN=<your-vault-token>
export VAULT_SKIP_VERIFY=true

# Run playbook
ansible-playbook -i inventory playbook.yml
```

### Method 2: Using Userpass Authentication (Recommended for Automation)

```bash
# Login with userpass to get token
export VAULT_ADDR=https://vault.lab.thewortmans.org:8200
vault login -method=userpass username=ansible

# Run playbook with retrieved token
ansible-playbook -i inventory playbook.yml
```

### Method 3: Using Ansible Vault for Vault Password

Store your Vault password in Ansible Vault (yes, using Ansible Vault to protect Vault password!):

```bash
# Encrypt the Vault password
ansible-vault encrypt_string 'your-vault-password' --name 'vault_password'

# Add to group_vars/all/vault.yml
vault_password: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          ...
```

## Using Vault Secrets in Playbooks

### Option 1: community.hashi_vault Plugin

```yaml
---
- name: Use Vault secrets
  hosts: all

  tasks:
    - name: Get secret from Vault
      set_fact:
        my_secret: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/apps/myapp:api_key') }}"
      no_log: true
```

### Option 2: URI Module (No Additional Dependencies)

```yaml
---
- name: Get secret via Vault API
  uri:
    url: "{{ vault_addr }}/v1/secret/data/homelab/apps/myapp"
    method: GET
    headers:
      X-Vault-Token: "{{ vault_token }}"
    validate_certs: no
  register: vault_response
  no_log: true

- name: Extract secret
  set_fact:
    my_secret: "{{ vault_response.json.data.data.api_key }}"
  no_log: true
```

### Option 3: Vault CLI

```yaml
---
- name: Get secret using CLI
  shell: vault kv get -field=api_key secret/homelab/apps/myapp
  register: secret
  changed_when: false
  no_log: true
```

## Common Patterns

### Pattern 1: Dynamic Inventory with Vault

```yaml
---
- name: Configure hosts with credentials from Vault
  hosts: all

  tasks:
    - name: Retrieve credentials
      set_fact:
        db_password: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/databases/mysql:root_password') }}"
      no_log: true

    - name: Configure application
      template:
        src: config.j2
        dest: /etc/app/config.yml
      no_log: true
```

### Pattern 2: Multiple Secrets at Once

```yaml
---
- name: Get multiple secrets
  set_fact:
    freenas_api_key: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/freenas/credentials:api_key') }}"
    freenas_password: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/freenas/credentials:root_password') }}"
    elasticsearch_password: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/elasticsearch/passwords:elastic_password') }}"
  no_log: true
```

### Pattern 3: Conditional Secret Retrieval

```yaml
---
- name: Get environment-specific secrets
  set_fact:
    api_key: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/homelab/apps/{{ app_name }}:api_key') }}"
  when: app_name is defined
  no_log: true
```

## Example Playbooks

See `vault-integration-example.yml` for complete examples.

## Troubleshooting

### Error: "Failed to authenticate with Vault"

```bash
# Check Vault status
vault status

# Verify token is valid
vault token lookup

# Check token has correct permissions
vault token capabilities secret/data/homelab/apps/myapp
```

### Error: "hvac library not found"

```bash
# Install hvac
pip install hvac

# For system Python
sudo pip3 install hvac
```

### Error: "SSL verification failed"

Set `VAULT_SKIP_VERIFY=true` for self-signed certificates (development only):

```bash
export VAULT_SKIP_VERIFY=true
```

For production, use proper TLS certificates:

```yaml
lookup_url: "{{ vault_addr }}"
ca_cert: /path/to/ca.crt
```

## Security Best Practices

1. **Never log secrets**: Always use `no_log: true` on tasks handling secrets
2. **Use service accounts**: Create dedicated Vault users for Ansible
3. **Limit permissions**: Use Vault policies to restrict access
4. **Rotate tokens**: Regularly rotate Vault authentication tokens
5. **Audit access**: Enable Vault audit logging

## Migration from Ansible Vault

To migrate existing Ansible Vault secrets to HashiCorp Vault:

```bash
# 1. Decrypt Ansible Vault file
ansible-vault decrypt group_vars/all/vault.yml

# 2. Extract secrets and put in Vault
vault kv put secret/homelab/apps/myapp \
    api_key="value-from-ansible-vault"

# 3. Remove from Ansible Vault file
# 4. Update playbooks to use Vault lookup

# 5. Re-encrypt remaining Ansible Vault file (if needed)
ansible-vault encrypt group_vars/all/vault.yml
```

## Quick Reference

```bash
# Read secret
vault kv get secret/homelab/apps/myapp

# Write secret
vault kv put secret/homelab/apps/myapp api_key=abc123

# Delete secret
vault kv delete secret/homelab/apps/myapp

# List secrets
vault kv list secret/homelab/apps/

# Get specific field
vault kv get -field=api_key secret/homelab/apps/myapp
```
