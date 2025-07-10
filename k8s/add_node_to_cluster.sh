#!/bin/sh

curl -sfL https://get.k3s.io | K3S_URL=https://km02.lab.thewortmans.org:6443 K3S_TOKEN=***REMOVED*** sh -
