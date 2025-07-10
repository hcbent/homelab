#!/bin/sh

curl -sfL https://get.k3s.io | sh -s - server --write-kubeconfig-mode 644 --tls-san km02.lab.thewortmans.org --tls-san km02 --tls-san 192.168.1.183 --tls-san km02.local
