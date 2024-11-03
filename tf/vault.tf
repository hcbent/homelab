# vault.tf

# Retrieve PM_USER from Vault
data "vault_generic_secret" "pm_user" {
  path = "secret/pm_user"
}

# Retrieve PM_PASS from Vault
data "vault_generic_secret" "pm_pass" {
  path = "secret/pm_pass"
}

# Use the secrets in a resource, output, or variable
# output "pm_user" {
#   value = data.vault_generic_secret.pm_user.data["PM_USER"]
# }

# output "pm_pass" {
#   value = data.vault_generic_secret.pm_pass.data["PM_PASS"]
# }
