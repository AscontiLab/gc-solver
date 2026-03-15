from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema():
    """Fehlende Spalten fuer bestehende SQLite-DBs nachziehen."""
    required_columns = {
        "research_source_type": "ALTER TABLE puzzle_solves ADD COLUMN research_source_type VARCHAR(50)",
        "research_url": "ALTER TABLE puzzle_solves ADD COLUMN research_url VARCHAR(500)",
        "research_summary": "ALTER TABLE puzzle_solves ADD COLUMN research_summary VARCHAR(200)",
        "research_excerpt": "ALTER TABLE puzzle_solves ADD COLUMN research_excerpt TEXT",
        "extracted_facts_json": "ALTER TABLE puzzle_solves ADD COLUMN extracted_facts_json TEXT",
        "variable_resolution_json": "ALTER TABLE puzzle_solves ADD COLUMN variable_resolution_json TEXT",
        "structured_solution_json": "ALTER TABLE puzzle_solves ADD COLUMN structured_solution_json TEXT",
    }

    with engine.begin() as conn:
        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(puzzle_solves)")).fetchall()
        }
        for column, ddl in required_columns.items():
            if column not in columns:
                conn.execute(text(ddl))
