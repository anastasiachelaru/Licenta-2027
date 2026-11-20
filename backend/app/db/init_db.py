"""Database initialization script: enables pgvector and creates all tables."""

from sqlalchemy import text
from backend.app.db.session import engine, Base
import backend.app.db.models  # noqa: F401


def init_database():
    """Create extensions and tables."""
    print("🔌 Connecting to database...")
    with engine.connect() as conn:
        print("⚙️ Ensuring 'vector' extension is enabled...")
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()
        
        result = conn.execute(text("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';")).fetchone()
        if result:
            print(f"✅ Extension pgvector enabled! Version: {result[1]}")
        else:
            print("❌ pgvector extension was not found.")

    print("🛠️ Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ All tables created successfully!")


if __name__ == "__main__":
    init_database()

