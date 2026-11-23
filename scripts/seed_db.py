"""Database Seeding Script for ErasmusMatch (Multi-University & Idempotent).

Loads parsed curricula from all JSON files in data/processed/*_courses.json,
computes dense multilingual semantic vectors using sentence-transformers,
and inserts everything into PostgreSQL with pgvector support and HNSW indexing.
"""

import json
import os
import sys
import glob
from typing import List, Dict, Any
from sqlalchemy import text

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

from backend.app.db.session import SessionLocal, engine
from backend.app.db.models import University, StudyProgram, Course, CourseEmbedding
from backend.app.models.canonical import CanonicalCourse, CurriculumPackage
from backend.app.services.embedding_service import embedding_service
from backend.app.db.init_db import init_database


# Metadata dictionary for universities
UNIVERSITY_METADATA: Dict[str, Dict[str, str]] = {
    "Universitatea Alexandru Ioan Cuza (UAIC)": {
        "country": "Romania",
        "city": "Iași",
        "erasmus_code": "RO IASI02",
        "website": "https://www.info.uaic.ro"
    },
    "Universidad Complutense de Madrid (UCM)": {
        "country": "Spain",
        "city": "Madrid",
        "erasmus_code": "E MADRID03",
        "website": "https://informatica.ucm.es"
    },
    "European University Cyprus (EUC)": {
        "country": "Cyprus",
        "city": "Nicosia",
        "erasmus_code": "CY NICOSIA24",
        "website": "https://euc.ac.cy"
    }
}


def seed_all_curricula(processed_dir: str = "data/processed"):
    """Reads all *_courses.json files, computes embeddings, and saves idempotently to PostgreSQL."""
    print("🚀 Starting multi-university database seeding pipeline...")

    # 1. Ensure DB extension & tables exist
    init_database()

    json_files = sorted(glob.glob(os.path.join(processed_dir, "*_courses.json")))
    if not json_files:
        raise FileNotFoundError(f"No *_courses.json files found in {processed_dir}.")

    print(f"📦 Found {len(json_files)} curriculum file(s) to process: {[os.path.basename(f) for f in json_files]}")

    db = SessionLocal()
    try:
        for json_path in json_files:
            print(f"\n{'='*60}")
            print(f"📂 Processing: {os.path.basename(json_path)}")
            print(f"{'='*60}")

            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            curriculum = CurriculumPackage(**data)
            uni_name = curriculum.university_name
            meta = UNIVERSITY_METADATA.get(uni_name, {
                "country": "International",
                "city": "Unknown",
                "erasmus_code": f"ERASMUS_{abs(hash(uni_name)) % 100000}",
                "website": "https://erasmus-plus.ec.europa.eu"
            })

            # 2. Upsert University
            uni = db.query(University).filter_by(erasmus_code=meta["erasmus_code"]).first()
            if not uni:
                uni = db.query(University).filter_by(name=uni_name).first()

            if not uni:
                uni = University(
                    name=uni_name,
                    country=meta["country"],
                    city=meta["city"],
                    erasmus_code=meta["erasmus_code"],
                    website=meta["website"]
                )
                db.add(uni)
                db.flush()
                print(f"🏛️ Created University: {uni.name} ({uni.erasmus_code}) [ID: {uni.id}]")
            else:
                uni.name = uni_name
                uni.country = meta["country"]
                uni.city = meta["city"]
                uni.website = meta["website"]
                db.flush()
                print(f"🏛️ University exists/updated: {uni.name} ({uni.erasmus_code}) [ID: {uni.id}]")

            # 3. Upsert Study Program
            program = db.query(StudyProgram).filter_by(
                university_id=uni.id,
                name=curriculum.study_program
            ).first()

            if not program:
                program = StudyProgram(
                    university_id=uni.id,
                    name=curriculum.study_program,
                    degree_cycle=curriculum.degree_cycle,
                    academic_year=curriculum.academic_year or "2023-2024"
                )
                db.add(program)
                db.flush()
                print(f"🎓 Created Study Program: {program.name} [ID: {program.id}]")
            else:
                program.degree_cycle = curriculum.degree_cycle
                program.academic_year = curriculum.academic_year or program.academic_year
                db.flush()
                print(f"🎓 Study Program exists: {program.name} [ID: {program.id}]")

            # 4. Upsert Courses and identify missing embeddings
            courses_needing_embeddings: List[Course] = []
            texts_to_embed: List[str] = []

            for c in curriculum.courses:
                # Find course by code (if exists) or title
                db_course = None
                if c.code:
                    db_course = db.query(Course).filter_by(
                        program_id=program.id,
                        code=c.code
                    ).first()

                if not db_course:
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
                    # Update metadata
                    db_course.code = c.code or db_course.code
                    db_course.title_en = c.title_en or db_course.title_en
                    db_course.ects = c.ects
                    db_course.semester = c.semester
                    db_course.year_of_study = c.year_of_study
                    db_course.language = c.language
                    db_course.course_type = c.course_type
                    db_course.optional_package = c.optional_package
                    db_course.description = c.description
                    db_course.objectives = c.objectives
                    db_course.topics_lecture = c.topics_lecture
                    db_course.topics_seminar_lab = c.topics_seminar_lab
                    db_course.competencies = c.competencies

                text_repr = c.to_embedding_text()

                # Check if embedding exists and is up to date
                emb_record = db.query(CourseEmbedding).filter_by(course_id=db_course.id).first()
                if not emb_record or emb_record.text_representation != text_repr:
                    courses_needing_embeddings.append(db_course)
                    texts_to_embed.append(text_repr)

            # 5. Compute embeddings in batch for courses needing them
            if texts_to_embed:
                print(f"🧠 Computing multilingual vectors for {len(texts_to_embed)} new/updated courses in '{uni.name}'...")
                vectors = embedding_service.embed_batch(texts_to_embed, batch_size=16)

                print("💾 Saving embeddings to pgvector...")
                for course_obj, text_repr, vec in zip(courses_needing_embeddings, texts_to_embed, vectors):
                    emb_rec = db.query(CourseEmbedding).filter_by(course_id=course_obj.id).first()
                    if not emb_rec:
                        emb_rec = CourseEmbedding(
                            course_id=course_obj.id,
                            text_representation=text_repr,
                            embedding=vec
                        )
                        db.add(emb_rec)
                    else:
                        emb_rec.text_representation = text_repr
                        emb_rec.embedding = vec
            else:
                print(f"✨ All {len(curriculum.courses)} courses in '{uni.name}' already have up-to-date embeddings!")

            db.commit()

        # 6. Ensure HNSW index exists
        print("\n⚡ Ensuring HNSW cosine index is active...")
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS course_embeddings_hnsw_idx "
                "ON course_embeddings USING hnsw (embedding vector_cosine_ops);"
            ))
            conn.commit()
        print("✅ HNSW index verified!")

    except Exception as e:
        db.rollback()
        print(f"❌ Error during seeding: {e}")
        raise e
    finally:
        db.close()


def print_database_summary():
    """Prints total course counts per university and program in PostgreSQL."""
    print("\n" + "=" * 65)
    print("📊 REZUMAT BAZĂ DE DATE (PostgreSQL + pgvector)")
    print("=" * 65)
    db = SessionLocal()
    try:
        sql = text("""
            SELECT u.name, u.erasmus_code, u.country, count(c.id) as total_courses
            FROM universities u
            JOIN study_programs sp ON u.id = sp.university_id
            JOIN courses c ON sp.id = c.program_id
            GROUP BY u.id, u.name, u.erasmus_code, u.country
            ORDER BY u.id;
        """)
        rows = db.execute(sql).fetchall()
        total_all = 0
        for r in rows:
            name, code, country, count = r
            total_all += count
            print(f"🏛️ {name} [{code}] ({country}): {count} cursuri")
        print("-" * 65)
        print(f"⭐ TOTAL GENERAL: {total_all} cursuri cu reprezentare vectorială (384 dim)")
        print("=" * 65)
    finally:
        db.close()


def test_cross_university_similarity():
    """Tests semantic matching between UAIC courses and the newly added UCM & EUC courses."""
    print("\n" + "=" * 65)
    print("🌍 TEST DE POTRIVIRE SEMANTICĂ TRANS-UNIVERSITARĂ")
    print("=" * 65)

    test_course_titles = ["Software Engineering", "Databases"]
    db = SessionLocal()
    try:
        for title in test_course_titles:
            # Find the UAIC course
            uaic_course = db.query(Course).join(StudyProgram).join(University).filter(
                University.erasmus_code == "RO IASI02",
                Course.title.ilike(f"%{title}%")
            ).first()

            if not uaic_course or not uaic_course.embedding:
                print(f"⚠️ Cursul UAIC '{title}' nu a fost găsit.")
                continue

            uaic_vec = uaic_course.embedding.embedding

            print(f"\n📘 Curs Sursă (UAIC): {uaic_course.title} ({uaic_course.ects} ECTS, Sem {uaic_course.semester})")
            print("   ------------------------------------------------------------")

            # Match against UCM (Universidad Complutense de Madrid)
            sql_ucm = text("""
                SELECT c.code, c.title, c.title_en, c.ects, c.semester, c.language,
                       1 - (ce.embedding <=> CAST(:query_vector AS vector)) AS similarity
                FROM courses c
                JOIN course_embeddings ce ON c.id = ce.course_id
                JOIN study_programs sp ON c.program_id = sp.id
                JOIN universities u ON sp.university_id = u.id
                WHERE u.erasmus_code = 'E MADRID03'
                ORDER BY ce.embedding <=> CAST(:query_vector AS vector)
                LIMIT 3;
            """)
            matches_ucm = db.execute(sql_ucm, {"query_vector": str(uaic_vec)}).fetchall()

            print("   🇪🇸 Top 3 Potriviri la UCM (Madrid):")
            for rank, m in enumerate(matches_ucm, 1):
                code, c_title, c_title_en, ects, sem, lang, sim = m
                pct = round(sim * 100, 1)
                print(f"      {rank}. [{code}] {c_title} (EN: {c_title_en})")
                print(f"         Compatibilitate: {pct}% | {ects} ECTS | Sem {sem} | Limba: {lang}")

            # Match against EUC (European University Cyprus)
            sql_euc = text("""
                SELECT c.code, c.title, c.title_en, c.ects, c.semester, c.language,
                       1 - (ce.embedding <=> CAST(:query_vector AS vector)) AS similarity
                FROM courses c
                JOIN course_embeddings ce ON c.id = ce.course_id
                JOIN study_programs sp ON c.program_id = sp.id
                JOIN universities u ON sp.university_id = u.id
                WHERE u.erasmus_code = 'CY NICOSIA24'
                ORDER BY ce.embedding <=> CAST(:query_vector AS vector)
                LIMIT 3;
            """)
            matches_euc = db.execute(sql_euc, {"query_vector": str(uaic_vec)}).fetchall()

            print("   🇨🇾 Top 3 Potriviri la EUC (Cipru):")
            for rank, m in enumerate(matches_euc, 1):
                code, c_title, c_title_en, ects, sem, lang, sim = m
                pct = round(sim * 100, 1)
                print(f"      {rank}. [{code}] {c_title}")
                print(f"         Compatibilitate: {pct}% | {ects} ECTS | Sem {sem} | Limba: {lang}")

    finally:
        db.close()
    print("\n" + "=" * 65)


if __name__ == "__main__":
    seed_all_curricula()
    print_database_summary()
    test_cross_university_similarity()
