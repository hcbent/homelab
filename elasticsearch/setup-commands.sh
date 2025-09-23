#!/bin/bash

# Elasticsearch setup commands for sparse vector RAG
ES_URL="https://es01.lab.thewortmans.org:9200"
ELASTIC_PASSWORD=$(cat ~/ELASTIC_PASSWORD)

echo "Setting up sparse vector RAG for python-rag-data index..."

# 1. Deploy ELSER model (if not already deployed)
echo "Deploying ELSER model..."
curl -skX POST "$ES_URL/_ml/trained_models/.elser_model_2/deployment/_start" \
  -H "Content-Type: application/json" \
  -u "elastic:$ELASTIC_PASSWORD"

# 2. Create the ingest pipeline
echo "Creating ingest pipeline..."
curl -skX PUT "$ES_URL/_ingest/pipeline/python-rag-embedding-pipeline" \
  -H "Content-Type: application/json" \
  -u "elastic:$ELASTIC_PASSWORD" \
  -d @ingest-pipeline.json

# 3. Create new index with updated mapping
echo "Creating new index with sparse vector mapping..."
curl -skX PUT "$ES_URL/python-rag-data-v2" \
  -H "Content-Type: application/json" \
  -u "elastic:$ELASTIC_PASSWORD" \
  -d @updated-mapping.json

# 4. Reindex data with embeddings
echo "Starting reindex operation (this may take a while)..."
curl -skX POST "$ES_URL/_reindex?wait_for_completion=false" \
  -H "Content-Type: application/json" \
  -u "elastic:$ELASTIC_PASSWORD" \
  -d @reindex-script.json

echo "Setup complete! Monitor reindex progress with:"
echo "curl -sku 'elastic:$ELASTIC_PASSWORD' $ES_URL/_tasks?actions=*reindex"