#!/usr/bin/env python3
"""
Debug script to test InfluxDB2 connection and data insertion
"""
import os
from datetime import datetime
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from dotenv import load_dotenv

load_dotenv()

# Get credentials
INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.environ.get("INFLUXDB_TOKEN")
INFLUXDB_ORG = os.environ.get("INFLUXDB_ORG")
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET")

print("=== InfluxDB2 Debug Script ===")
print(f"URL: {INFLUXDB_URL}")
print(f"Org: {INFLUXDB_ORG}")
print(f"Bucket: {INFLUXDB_BUCKET}")
print(f"Token: {'***' + INFLUXDB_TOKEN[-4:] if INFLUXDB_TOKEN else 'NOT SET'}")
print()

def test_connection():
    """Test basic connection to InfluxDB2"""
    try:
        with InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG) as client:
            # Test connection by checking health
            health = client.health()
            print(f"✓ InfluxDB Health: {health.status}")
            
            # List buckets to verify access
            buckets_api = client.buckets_api()
            buckets = buckets_api.find_buckets()
            print(f"✓ Available buckets: {[b.name for b in buckets.buckets]}")
            
            # Check if our bucket exists
            bucket_exists = any(b.name == INFLUXDB_BUCKET for b in buckets.buckets)
            print(f"✓ Target bucket '{INFLUXDB_BUCKET}' exists: {bucket_exists}")
            
            return True
            
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        return False

def test_write():
    """Test writing a sample record"""
    try:
        with InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG) as client:
            write_api = client.write_api(write_options=SYNCHRONOUS)
            
            # Create a test point
            point = Point("test_measurement") \
                .tag("source", "debug_script") \
                .field("test_value", 123.45) \
                .time(datetime.utcnow())
            
            # Write the point
            write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
            print("✓ Test write successful")
            return True
            
    except Exception as e:
        print(f"✗ Write failed: {e}")
        return False

def test_read():
    """Test reading data from the bucket"""
    try:
        with InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG) as client:
            query_api = client.query_api()
            
            # Query for any data in the last 24 hours
            query = f'''
            from(bucket: "{INFLUXDB_BUCKET}")
              |> range(start: -24h)
              |> limit(n: 10)
            '''
            
            result = query_api.query(query)
            record_count = 0
            
            for table in result:
                for record in table.records:
                    record_count += 1
                    print(f"Record: {record.get_measurement()} | {record.get_field()}={record.get_value()} | {record.get_time()}")
            
            print(f"✓ Found {record_count} records in last 24h")
            
            # Specifically check for whale_transactions
            whale_query = f'''
            from(bucket: "{INFLUXDB_BUCKET}")
              |> range(start: -24h)
              |> filter(fn: (r) => r["_measurement"] == "whale_transactions")
              |> limit(n: 10)
            '''
            
            whale_result = query_api.query(whale_query)
            whale_count = 0
            
            for table in whale_result:
                for record in table.records:
                    whale_count += 1
            
            print(f"✓ Found {whale_count} whale_transactions records")
            return True
            
    except Exception as e:
        print(f"✗ Read failed: {e}")
        return False

if __name__ == "__main__":
    if not all([INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET]):
        print("✗ Missing required environment variables")
        print("Required: INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET")
        exit(1)
    
    print("1. Testing connection...")
    if not test_connection():
        exit(1)
    
    print("\n2. Testing write...")
    if not test_write():
        exit(1)
    
    print("\n3. Testing read...")
    test_read()
    
    print("\n=== Debug Complete ===")