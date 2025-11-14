#!/bin/sh

# Replace CHANGEME_K3S_TOKEN with your actual K3S cluster token
# Get token from master node: sudo cat /var/lib/rancher/k3s/server/node-token
curl -sfL https://get.k3s.io | K3S_URL=https://km02.lab.thewortmans.org:6443 K3S_TOKEN=CHANGEME_K3S_TOKEN sh -
