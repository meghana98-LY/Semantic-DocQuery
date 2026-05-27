import os
import sys
from dotenv import load_dotenv

# Ensure backend package path is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

load_dotenv(os.path.join(BASE_DIR, '..', '.env'))

from database import SessionLocal
from models import Document


def main(limit=20):
    db = SessionLocal()
    try:
        docs = db.query(Document).order_by(Document.created_at.desc()).limit(limit).all()
        print(f"Last {len(docs)} documents:")
        for d in docs:
            print(f"id={d.id} filename={d.filename} status={d.status} created_at={d.created_at}")
    finally:
        db.close()


if __name__ == '__main__':
    main()
