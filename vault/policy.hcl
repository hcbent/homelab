# policy.hcl
path "secret/data/pm_user" {
  capabilities = ["read"]
}

path "secret/data/pm_pass" {
  capabilities = ["read"]
}

