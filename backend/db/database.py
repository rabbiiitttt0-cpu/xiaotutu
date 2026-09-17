"""数据库连接与 session 管理（SQLite 开发 / PostgreSQL 生产）"""
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"


def _resolve_db_url() -> str:
    """env > data/pg_config.json > SQLite 兜底（删除 pg_config.json 即回退 SQLite）"""
    env = os.getenv("DATABASE_URL")
    if env:
        return env
    pg_cfg = DATA_DIR / "pg_config.json"
    if pg_cfg.exists():
        try:
            cfg = json.loads(pg_cfg.read_text(encoding="utf-8"))
            pwd = cfg.get("password", "")
            if pwd and "在这里" not in pwd:
                return (
                    f"postgresql+psycopg2://{cfg['user']}:{pwd}"
                    f"@{cfg['host']}:{cfg.get('port', 5432)}/{cfg['dbname']}"
                )
        except (json.JSONDecodeError, KeyError, OSError):
            pass
    return f"sqlite:///{DATA_DIR / 'app.db'}"


DATABASE_URL = _resolve_db_url()

connect_args = {}
engine_kwargs = {"connect_args": connect_args, "echo": False}
if "sqlite" in DATABASE_URL:
    connect_args["check_same_thread"] = False
else:
    engine_kwargs.update({
        "pool_size": 10, "max_overflow": 20, "pool_timeout": 30,
        "pool_recycle": 1800, "pool_pre_ping": True,
    })

engine = create_engine(DATABASE_URL, **engine_kwargs)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in DATABASE_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """依赖注入的数据库 session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """建表（用户 + 日志；识图网站无 vector/pg_trgm 扩展）"""
    from .models import audit_log  # noqa: F401
    from auth import models as auth_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
