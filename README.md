# homelab
Homelab configuration files

## Setup
Download this repo to your chosen location and then run `terraform init` to download the providers and make sure everything is ready to go.

```bash
terraform init
```

## Usage
### Configuration
Edit the homelab.tfvars file and add whatever VMs you want to create.

Then, use `terraform plan -var-file homelab.tfvars` to ensure your vars are syntactically correct. If you're happy with the plan results, then:

```bash
terraform apply -var-file homelab.tfvars
```

## Roadmap
Expansion ideas:
- Module proxmox_lxc for adding LXC containers
- K8s

