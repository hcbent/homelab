provider "proxmox" {
    pm_api_url = var.pm_api_url
    pm_user = var.pm_user
    pm_password = var.pm_password
    pm_tls_insecure = var.pm_tls_insecure
}

provider "vault" {
  address = "http://127.0.0.1:8200" # Replace with your Vault address
#   auth_login {
#     path = "auth/aws/login"
#     parameters = {
#       role = "your-aws-role"
#     }
#   }
}
