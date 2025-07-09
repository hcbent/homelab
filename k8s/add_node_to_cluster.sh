#!/bin/sh

curl -sfL https://get.k3s.io | K3S_URL=https://km02.lab.thewortmans.org:6443 K3S_TOKEN=K1084e4fbe94f9a7af153f53579567a4c79214fe8641cc0073edcd5c696a2734957::server:bc04b89a13f1ba9207d933d540575a41 sh -
