#!/bin/bash
#
# Source this file for some shortcuts to common terraform operations which
# take the cluster name as input, assuming there are or will be 
# cluster_name.tfvars and cluster_name.tfstate files.
#
# V0.1 | 5 Jan 2024 | Bret Wortman
#

export PLUGIN_DIR=/elastic/.terraform.d/plugins
alias gotf='cd /elastic/asg/terraform-asg'

function tfp {
    terraform plan -var-file ${1%.tfvars}.tfvars -state ${1%.tfvars}.tfstate ${2}
}
function tfa {
    terraform apply -var-file ${1%.tfvars}.tfvars -state ${1%.tfvars}.tfstate ${2}
}
function tfd {
    terraform destroy -var-file ${1%.tfvars}.tfvars -state ${1%.tfvars}.tfstate ${2}
}