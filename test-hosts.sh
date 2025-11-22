#!/bin/bash

test_host() {
	HOST=$1
	echo "===== Testing $HOST ====="
	curl -I http://$HOST.home.lab/
}

test_host actual
test_host argocd
test_host cerebro
test_host df
test_host dfk
test_host elasticsearch
test_host kibana
test_host mealie
test_host monitoring
test_host paperless
test_host pihole
test_host plex
test_host qbt
test_host radarr
test_host sonarr
