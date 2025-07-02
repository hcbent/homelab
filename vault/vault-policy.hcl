# need these paths to grant permissions:
path "secret/data/*" {
  capabilities = ["create", "update"]
}
