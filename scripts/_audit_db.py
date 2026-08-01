import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from sqlalchemy import inspect, text
from app.core.database import SessionLocal

db = SessionLocal()
try:
    inspector = inspect(db.bind)
    tables = inspector.get_table_names()
    print("TABLES:", tables)
    for t in tables:
        cols = inspector.get_columns(t)
        col_names = [c["name"] for c in cols]
        count = db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
        print(f"\n===== TABLE: {t} (rows={count}) =====")
        print("COLUMNS:", col_names)
        if count:
            rows = db.execute(text(f'SELECT * FROM "{t}"')).fetchall()
            for r in rows:
                rec = {}
                for cname, val in zip(col_names, r):
                    rec[cname] = str(val)
                print(json.dumps(rec, ensure_ascii=False))
except Exception as e:
    import traceback
    traceback.print_exc()
finally:
    db.close()
