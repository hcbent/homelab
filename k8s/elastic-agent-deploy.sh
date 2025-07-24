curl -L -O https://artifacts.elastic.co/downloads/beats/elastic-agent/elastic-agent-8.18.1-linux-x86_64.tar.gz 
tar xzvf elastic-agent-8.18.1-linux-x86_64.tar.gz
cd elastic-agent-8.18.1-linux-x86_64
sudo ./elastic-agent install --url=https://fleet.lab.thewortmans.org:8220 --enrollment-token=NV9KekVaY0I0cHVqS0lGZ0hzZVM6MkxPb050NERPZklNLUVWZHhhZk5Edw== --unprivileged
