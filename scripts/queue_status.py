import os
import sys

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.core.redis import get_redis_client
from app.tasks.celery_app import celery_app

def check_queue_status():
    print("=" * 65)
    print(" 📊 CELERY & REDIS QUEUE STATUS MONITOR")
    print("=" * 65)
    
    try:
        redis_client = get_redis_client()
        pending_count = redis_client.llen("celery")
        print(f" ⏳ Pending Tasks Waiting in Redis Queue:  {pending_count}")
    except Exception as e:
        print(f" ❌ Redis Connection Error: {e}")
        pending_count = 0

    print("-" * 65)
    print(" 📡 Inspecting Running Celery Worker Nodes...")
    
    try:
        insp = celery_app.control.inspect(timeout=3)
        active_tasks = insp.active()
        reserved_tasks = insp.reserved()
        stats = insp.stats()
        
        if not stats:
            print(" ⚠️ No active Celery worker nodes detected.")
            print("    (Start worker with: python -m celery -A app.tasks.celery_app worker --pool=solo -l info)")
        else:
            for worker_name, tasks in (active_tasks or {}).items():
                print(f"\n 🟢 Worker Node: {worker_name}")
                print(f"    Active Running Tasks:   {len(tasks)}")
                for t in tasks:
                    args = t.get("args", [])
                    url = args[0] if args else "N/A"
                    print(f"     -> Running: [ID: {t.get('id')[:8]}] {t.get('name')} | URL: {url}")
                    
            for worker_name, tasks in (reserved_tasks or {}).items():
                print(f"    Reserved Queue Tasks:   {len(tasks)}")
                
    except Exception as e:
        print(f" ⚠️ Could not inspect Celery worker: {e}")
        
    print("\n" + "=" * 65)

if __name__ == "__main__":
    check_queue_status()
