from app.tasks.celery_app import celery_app

@celery_app.task(name="tasks.ping_test")
def ping_test(message: str) -> dict:
    """Simple test task to verify Celery task publishing and execution."""
    print(f"Executing ping_test task with message: {message}")
    return {
        "status": "success",
        "message": f"Pong! Successfully received: {message}"
    }
