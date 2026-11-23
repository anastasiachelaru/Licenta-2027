"""Interactive Semantic Search CLI for ErasmusMatch.

Allows testing multilingual similarity queries against PostgreSQL + pgvector
directly from the terminal.
"""

import sys
import os
from sqlalchemy import text

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

from backend.app.db.session import SessionLocal
from backend.app.services.embedding_service import embedding_service


def search_courses(query_text: str, top_k: int = 5):
    """Encodes query and retrieves top_k semantically similar courses from pgvector."""
    db = SessionLocal()
    try:
        # 1. Compute query embedding vector
        query_vector = embedding_service.embed_text(query_text)

        # 2. Query pgvector using cosine distance (<=>)
        sql = text("""
            SELECT c.title, c.ects, c.semester, c.course_type, c.language, u.name as uni_name,
                   1 - (ce.embedding <=> CAST(:query_vector AS vector)) AS similarity,
                   c.objectives
            FROM courses c
            JOIN course_embeddings ce ON c.id = ce.course_id
            JOIN study_programs sp ON c.program_id = sp.id
            JOIN universities u ON sp.university_id = u.id
            ORDER BY ce.embedding <=> CAST(:query_vector AS vector)
            LIMIT :top_k;
        """)

        results = db.execute(sql, {
            "query_vector": str(query_vector),
            "top_k": top_k
        }).fetchall()

        print(f"\n" + "=" * 70)
        print(f"🔎 Căutare: \"{query_text}\"")
        print("=" * 70)

        for rank, r in enumerate(results, 1):
            title, ects, sem, c_type, lang, uni_name, score, objectives = r
            pct = round(score * 100, 1)
            bar = "█" * int(pct // 5) + "░" * (20 - int(pct // 5))

            print(f"\n{rank}. {title.upper()} ({uni_name})")
            print(f"   📊 Compatibilitate: [{bar}] {pct}%")
            print(f"   ℹ️ Semestru: {sem} | Credite: {ects} ECTS | Tip: {c_type} | Limba: {lang}")
            if objectives:
                first_obj = objectives.strip().split("\n")[0][:120]
                print(f"   🎯 Obiectiv: {first_obj}...")

        print("\n" + "=" * 70)

    finally:
        db.close()


def main():
    # If query passed as command-line arguments
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        search_courses(query)
        return

    # Interactive mode
    print("=" * 65)
    print("🎓 ErasmusMatch - Test Căutare Semantică Multilingvă")
    print("   (Scrie orice materie, temă sau concept în română, engleză,")
    print("    spaniolă etc. Tastează 'exit' sau 'q' pentru a ieși)")
    print("=" * 65)

    while True:
        try:
            query = input("\n👉 Introdu o căutare: ").strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit", "q"):
                print("La revedere! 👋")
                break
            search_courses(query)
        except (KeyboardInterrupt, EOFError):
            print("\nLa revedere! 👋")
            break


if __name__ == "__main__":
    main()

