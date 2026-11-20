"""Database Seeding Script for ErasmusMatch.

Loads parsed UAIC courses from data/processed/uaic_courses.json,
computes dense multilingual semantic vectors using sentence-transformers,
and inserts everything into PostgreSQL with pgvector support and HNSW indexing.
"""

import json
import os
import sys
from typing import List
from sqlalchemy import text

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

from backend.app.db.session import SessionLocal, engine
from backend.app.db.models import University, StudyProgram, Course, CourseEmbedding
from backend.app.models.canonical import CanonicalCourse, CurriculumPackage
from backend.app.services.embedding_service import embedding_service
from backend.app.db.init_db import init_database


def seed_database(json_path: str = "data/processed/uaic_courses.json"):
    """Reads JSON curriculum, computes embeddings, and saves to PostgreSQL."""
    print("🚀 Starting database seeding pipeline...")

    # 1. Ensure DB extension & tables exist
    init_database()

    # 2. Load JSON data
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Curriculum JSON not found at {json_path}. Run scripts/parser.py first.")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    curriculum = CurriculumPackage(**data)
    print(f"📄 Loaded {len(curriculum.courses)} courses for '{curriculum.university_name}'.")

    db = SessionLocal()
    try:
        # 3. Create or get University
        uni = db.query(University).filter_by(erasmus_code="RO IASI02").first()
        if not uni:
            uni = University(
                name="Universitatea Alexandru Ioan Cuza (UAIC)",
                country="Romania",
                city="Iași",
                erasmus_code="RO IASI02",
                website="https://www.info.uaic.ro"
            )
            db.add(uni)
            db.flush()
            print(f"🏛️ Created University: {uni.name} (ID: {uni.id})")
        else:
            print(f"🏛️ University already exists: {uni.name} (ID: {uni.id})")

        # 4. Create or get Study Program
        program = db.query(StudyProgram).filter_by(
            university_id=uni.id,
            name=curriculum.study_program
        ).first()
        if not program:
            program = StudyProgram(
                university_id=uni.id,
                name=curriculum.study_program,
                degree_cycle=curriculum.degree_cycle,
                academic_year=curriculum.academic_year or "2025-2026"
            )
            db.add(program)
            db.flush()
            print(f"🎓 Created Study Program: {program.name} (ID: {program.id})")
        else:
            print(f"🎓 Study Program already exists: {program.name} (ID: {program.id})")

        # 5. Prepare course texts for batch embedding
        embedding_texts: List[str] = []
        course_objects: List[Course] = []

        print("\n⏳ Preparing courses and generating multilingual embeddings...")
        for c in curriculum.courses:
            # Check if course already exists
            db_course = db.query(Course).filter_by(
                program_id=program.id,
                title=c.title
            ).first()

            if not db_course:
                db_course = Course(
                    program_id=program.id,
                    code=c.code,
                    title=c.title,
                    title_en=c.title_en or c.title,
                    ects=c.ects,
                    semester=c.semester,
                    year_of_study=c.year_of_study,
                    language=c.language,
                    course_type=c.course_type,
                    optional_package=c.optional_package,
                    description=c.description,
                    objectives=c.objectives,
                    topics_lecture=c.topics_lecture,
                    topics_seminar_lab=c.topics_seminar_lab,
                    competencies=c.competencies,
                    raw_text=c.raw_text
                )
                db.add(db_course)
                db.flush()
            else:
                # Update metadata if needed
                db_course.ects = c.ects
                db_course.semester = c.semester
                db_course.course_type = c.course_type
                db_course.objectives = c.objectives
                db_course.topics_lecture = c.topics_lecture
                db_course.topics_seminar_lab = c.topics_seminar_lab

            course_objects.append(db_course)
            embedding_texts.append(c.to_embedding_text())

        # 6. Generate vectors in batch
        print(f"🧠 Computing dense vectors for {len(embedding_texts)} courses using '{embedding_service.model_name}'...")
        vectors = embedding_service.embed_batch(embedding_texts, batch_size=16)

        # 7. Store embeddings in PostgreSQL
        print("💾 Saving embeddings to pgvector...")
        for course, text_repr, vec in zip(course_objects, embedding_texts, vectors):
            emb_record = db.query(CourseEmbedding).filter_by(course_id=course.id).first()
            if not emb_record:
                emb_record = CourseEmbedding(
                    course_id=course.id,
                    text_representation=text_repr,
                    embedding=vec
                )
                db.add(emb_record)
            else:
                emb_record.text_representation = text_repr
                emb_record.embedding = vec

        db.commit()
        print("✅ All courses and vector embeddings successfully saved!")

        # 8. Create HNSW Vector Index for ultra-fast Cosine Similarity
        print("⚡ Creating HNSW cosine index...")
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS course_embeddings_hnsw_idx "
                "ON course_embeddings USING hnsw (embedding vector_cosine_ops);"
            ))
            conn.commit()
        print("✅ HNSW index created!")

    except Exception as e:
        db.rollback()
        print(f"❌ Error during seeding: {e}")
        raise e
    finally:
        db.close()


def test_semantic_search():
    """Demonstrates cross-lingual semantic search using pgvector cosine distance."""
    print("\n🔍 Running Multilingual Semantic Search Verification...")
    test_queries = [
        ("Română", "Arhitectura calculatoarelor, sisteme de operare și gestiunea proceselor"),
        ("Română", "Baze de date relaționale, limbajul SQL și modelare ACID"),
        ("Spaniolă", "Algoritmos en grafos, caminos mínimos y estructuras de datos"),
        ("Engleză", "Deep neural networks, backpropagation and machine learning models"),
    ]

    db = SessionLocal()
    try:
        for lang, query_text in test_queries:
            query_vector = embedding_service.embed_text(query_text)

            # Query PostgreSQL pgvector: 1 - (embedding <=> :query_vector) is Cosine Similarity
            sql = text("""
                SELECT c.title, c.ects, c.semester, c.course_type,
                       1 - (ce.embedding <=> CAST(:query_vector AS vector)) AS similarity
                FROM courses c
                JOIN course_embeddings ce ON c.id = ce.course_id
                ORDER BY ce.embedding <=> CAST(:query_vector AS vector)
                LIMIT 3;
            """)

            results = db.execute(sql, {"query_vector": str(query_vector)}).fetchall()

            print(f"\n🔎 [{lang}] Query: \"{query_text}\"")
            for rank, r in enumerate(results, 1):
                title, ects, sem, c_type, score = r
                pct = round(score * 100, 1)
                print(f"   {rank}. {title} (Sem {sem}, {ects} ECTS) -> Compatibilitate: {pct}%")
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
    test_semantic_search()

