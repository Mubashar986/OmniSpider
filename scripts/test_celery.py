import os
import sys
import time

# Add parent directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.tasks.test_tasks import ping_test

def main():
    print("Dispatching test task to Celery queue via Upstash Redis...")
    async_result = ping_test.delay("Hello Celery & Upstash Redis!")
    print(f"Task dispatched successfully. Task ID: {async_result.id}")
    
    print("Waiting for task result (timeout 10s)...")
    try:
        result = async_result.get(timeout=10)
        print(f"Task completed successfully! Result: {result}")
    except Exception as e:
        print(f"Note: Could not get result synchronously (is worker running?): {e}")
        print("To run the Celery worker process on Windows, execute:")
        print("   celery -A app.tasks.celery_app worker --pool=solo -l info")

if __name__ == "__main__":
    main()
