import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from alembic.config import Config
from alembic import command

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.core.config import settings

def create_database_if_not_exists():
    """Ensure target database exists in PostgreSQL."""
    try:
        conn = psycopg2.connect(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            dbname="postgres"
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()
        
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (settings.POSTGRES_DB,))
        exists = cursor.fetchone()
        
        if not exists:
            print(f"Database '{settings.POSTGRES_DB}' not found. Creating database...")
            cursor.execute(f'CREATE DATABASE "{settings.POSTGRES_DB}";')
            print(f"Database '{settings.POSTGRES_DB}' created successfully.")
        else:
            print(f"Database '{settings.POSTGRES_DB}' already exists.")
            
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error checking/creating database: {e}")
        sys.exit(1)

def run_alembic_migrations():
    """Run Alembic upgrade head to apply database migrations."""
    print("Running Alembic migrations (upgrade head)...")
    try:
        alembic_cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
        command.upgrade(alembic_cfg, "head")
        print("Alembic migrations completed successfully.")
    except Exception as e:
        print(f"Alembic migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    create_database_if_not_exists()
    run_alembic_migrations()
