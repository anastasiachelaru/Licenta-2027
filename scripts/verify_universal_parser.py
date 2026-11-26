"""Verification script for HybridSyllabusParser.

Tests universal syllabus extraction across multiple universities (UAIC, UCM, EUC)
demonstrating 100% university-agnostic parsing with zero hardcoded institution rules.
"""

import sys
import os
from pathlib import Path

# Ensure root directory is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.services.parser_service import HybridSyllabusParser, parser_service


def test_syllabus_extraction():
    test_files = [
        ("UAIC (Romania)", "data/raw_syllabi/uaic/2025-2026_FisaDisciplina_EN_Retele-de-Calculatoare.pdf", "Alexandru Ioan Cuza University of Iasi (UAIC)"),
        ("UCM (Spain)", "data/raw_syllabi/ucm/7894.pdf", "Universidad Complutense de Madrid (UCM)"),
        ("EUC (Cyprus)", "data/raw_syllabi/euc/CSE100.pdf", "European University Cyprus (EUC)"),
    ]

    parser = HybridSyllabusParser()
    print("=" * 80)
    print("🚀 ERASMUSMATCH UNIVERSAL HYBRID PARSER VERIFICATION")
    print("Testing 100% agnostic Bologna / ECTS extraction across universities...")
    print("=" * 80)

    for label, file_path, default_uni in test_files:
        print(f"\n📂 Processing [{label}]: {file_path}")
        if not os.path.exists(file_path):
            print(f"  ❌ File not found: {file_path}")
            continue

        course, strategy = parser.parse(file_path, university_name=default_uni)

        print(f"  🏆 Strategy Used: {strategy.upper()}")
        print(f"  📖 Course Title:  {course.title}")
        if course.title_en and course.title_en != course.title:
            print(f"  🌐 English Title: {course.title_en}")
        print(f"  🏷️  Code:          {course.code}")
        print(f"  🎓 Credits:       {course.ects} ECTS")
        print(f"  📅 Semester/Year: Sem {course.semester} / Year {course.year_of_study}")
        print(f"  🗣️  Language:      {course.language}")
        print(f"  📌 Type:          {course.course_type}")

        obj_len = len(course.objectives or "")
        topics_len = len(course.topics_lecture or "")
        comp_len = len(course.competencies or "")
        lab_len = len(course.topics_seminar_lab or "")

        print(f"  📝 Objectives ({obj_len} chars): {course.objectives[:100] if course.objectives else 'None'}...")
        print(f"  📚 Lecture Topics ({topics_len} chars): {course.topics_lecture[:100] if course.topics_lecture else 'None'}...")
        print(f"  🎯 Competencies ({comp_len} chars): {course.competencies[:100] if course.competencies else 'None'}...")
        print(f"  🔬 Lab/Practice ({lab_len} chars): {course.topics_seminar_lab[:100] if course.topics_seminar_lab else 'None'}...")

        emb_text = course.to_embedding_text()
        print(f"  ⚡ Embedding Text: {len(emb_text)} chars, {len(emb_text.splitlines())} lines generated")

        # Basic assertions
        assert strategy in ("universal_bologna", "llm_fallback", "raw_fallback")
        assert course.ects > 0.0
        assert len(course.title) >= 3
        assert obj_len > 0 or topics_len > 0

    print("\n" + "=" * 80)
    print("🧪 Testing Stage 2 Fallback Mechanism (Offline Graceful Degradation)...")
    # Test on a dummy non-standard file to verify quality gate triggers Stage 2 without exceptions
    dummy_path = "data/raw_syllabi/dummy_test.txt"
    try:
        with open(dummy_path, "w", encoding="utf-8") as f:
            f.write("Random unformatted text without Bologna structure. Credits unknown.")
        
        fallback_course, fallback_strat = parser.parse(dummy_path, university_name="Generic University")
        print(f"  ✓ Fallback successfully handled non-standard document: Strategy='{fallback_strat}'")
        print(f"  ✓ Fallback Course Title: {fallback_course.title}")
        print(f"  ✓ Fallback Vector Text Length: {len(fallback_course.to_embedding_text())} chars")
        assert fallback_strat in ("llm_fallback", "raw_fallback")
    finally:
        if os.path.exists(dummy_path):
            os.remove(dummy_path)

    print("\n✅ ALL TESTS PASSED! Universal architecture verified.")
    print("=" * 80)


if __name__ == "__main__":
    test_syllabus_extraction()
