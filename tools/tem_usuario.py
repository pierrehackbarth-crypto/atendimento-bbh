import sys
from sqlalchemy import select, func
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from app.db import SessionLocal
from app.models import User
db = SessionLocal()
sys.exit(0 if (db.scalar(select(func.count()).select_from(User)) or 0) > 0 else 1)
