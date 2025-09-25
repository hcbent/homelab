import requests
import json
from datetime import datetime

def check_elasticsearch_connection(host="localhost", port=9200, protocol="http"):
    """Check if Elasticsearch is accessible"""
    url = f"{protocol}://{host}:{port}"
    
    try:
        # Test basic connectivity
        response = requests.get(f"{url}/", timeout=10)
        print(f"✓ Elasticsearch is accessible at {url}")
        print(f"Response: {response.json()}")
        return True
    except requests.exceptions.ConnectionError:
        print(f"✗ Connection refused to {url}")
        return False
    except requests.exceptions.Timeout:
        print(f"✗ Connection timeout to {url}")
        return False
    except Exception as e:
        print(f"✗ Error connecting to {url}: {e}")
        return False

# Test the connection
check_elasticsearch_connection()
