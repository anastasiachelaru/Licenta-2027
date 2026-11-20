"""Parser for University Syllabi (PDF to CanonicalCourse).

Extracts structured curriculum data from UAIC (Alexandru Ioan Cuza University)
Course Programme (Fișa disciplinei) PDFs into the unified CanonicalCourse schema.
"""

import os
import re
import glob
import json
from typing import List, Optional
from pathlib import Path
import pdfplumber

from backend.app.models.canonical import CanonicalCourse, CurriculumPackage


ROMAN_TO_INT = {
    "I": 1,
    "II": 2,
    "III": 3,
    "IV": 4,
    "V": 5,
    "VI": 6,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
}

TYPE_MAP = {
    "ob": "mandatory",
    "obligatory": "mandatory",
    "obligatoriu": "mandatory",
    "op": "optional",
    "optionally": "optional",
    "optional": "optional",
    "f": "facultative",
    "facultative": "facultative",
    "facultativ": "facultative",
}


class UAICPDFParser:
    """Extracts structured curriculum data from UAIC Course Programme (Fișa disciplinei) PDFs."""

    def __init__(self, university_name: str = "UAIC", default_program: str = "Computer Science"):
        self.university_name = university_name
        self.default_program = default_program

    def _clean_text(self, text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        text = text.replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_field(self, pattern: str, text: str, flags: int = 0) -> Optional[str]:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()
        return None

    def _parse_semester(self, text: str, filename: str) -> Optional[int]:
        # Try Section 2.5 Semester
        sem_match = re.search(r"2\.5\s*Semester\s*([IVX]+|\d+)", text, re.IGNORECASE)
        if sem_match:
            raw = sem_match.group(1).upper()
            if raw in ROMAN_TO_INT:
                return ROMAN_TO_INT[raw]

        # Fallback to filename patterns (e.g., sem_3, sem V)
        fn_match = re.search(r"sem(?:ester)?[\s_]*([IVX]+|\d+)", filename, re.IGNORECASE)
        if fn_match:
            raw = fn_match.group(1).upper()
            if raw in ROMAN_TO_INT:
                return ROMAN_TO_INT[raw]

        return None

    def _parse_year(self, text: str, semester: Optional[int]) -> Optional[int]:
        year_match = re.search(r"2\.4\s*Year\s*([IVX]+|\d+)", text, re.IGNORECASE)
        if year_match:
            raw = year_match.group(1).upper()
            if raw in ROMAN_TO_INT:
                return ROMAN_TO_INT[raw]

        if semester:
            return (semester + 1) // 2

        return None

    def _parse_course_type(self, text: str) -> str:
        match = re.search(r"2\.7\s*Course type\**\s*([A-Za-z]+)", text, re.IGNORECASE)
        if match:
            raw = match.group(1).lower()
            return TYPE_MAP.get(raw, "mandatory")
        return "mandatory"

    def _parse_ects(self, text: str) -> float:
        match = re.search(r"(?:3\.9\s*Credit points|Credit points|Num[aă]r(?:ul)? de credite)\s*[:.]?\s*(\d+(?:[.,]\d+)?)", text, re.IGNORECASE)
        if match:
            val = match.group(1).replace(",", ".")
            try:
                return float(val)
            except ValueError:
                pass
        return 5.0

    def _clean_table_topic_lines(self, raw_section_text: str) -> Optional[str]:
        """Extracts substantive syllabus topic lines, filtering headers, pagination noise and methods."""
        # Strip trailing bibliography from the section if present
        raw_cut = re.split(r"\n\s*Bibliography\b", raw_section_text, flags=re.IGNORECASE)[0]

        boilerplate_patterns = [
            "teaching methods", "remarks", "number oh hours", "references)",
            "course programme", "access to additional resources", "course website",
            "laboratory website", "fisa disciplinei"
        ]

        method_indicators = (
            r"\s*(?:Interactive presentations|Slides|blackboard|Online access|Direct interaction|"
            r"Lecturing|Slide presentation|Problem-based learning|Exercise|Conversational|"
            r"Heuristic conversation|Case study|Demonstration|Debate|Project-based).*$"
        )

        cleaned_lines = []
        for line in raw_cut.split("\n"):
            line_str = line.strip()
            if not line_str:
                continue

            # Skip table header lines and pagination artifacts
            if any(b in line_str.lower() for b in boilerplate_patterns):
                continue
            if re.match(r"^8\.[12]\s*(?:Course|Seminary)", line_str, re.IGNORECASE):
                continue

            # Strip teaching method & remarks columns
            line_str = re.sub(method_indicators, "", line_str, flags=re.IGNORECASE)
            # Strip trailing hours/references
            line_str = re.sub(r"\s*\d+\s*(?:,\s*see\b|\bhours?\b|\bore\b).*$", "", line_str, flags=re.IGNORECASE)
            line_str = re.sub(r"\s*see bibliography.*$", "", line_str, flags=re.IGNORECASE)
            line_str = line_str.strip()

            # Ignore short artifacts or fragments
            if len(line_str) > 3 and not line_str.lower().endswith("see"):
                # Avoid adjacent duplicate lines caused by page break repetitions
                if not cleaned_lines or cleaned_lines[-1] != line_str:
                    cleaned_lines.append(line_str)

        return "\n".join(cleaned_lines) if cleaned_lines else None

    def parse_pdf(self, file_path: str) -> CanonicalCourse:
        """Parses a single UAIC PDF syllabus into a CanonicalCourse model."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        full_pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                full_pages.append(page.extract_text() or "")

        full_text = "\n".join(full_pages)

        # 1. Course Title
        course_name = self._extract_field(r"2\.1\s*Course Name\s*(.+?)(?=\n\s*2\.2|$)", full_text, re.DOTALL)
        if course_name:
            course_name = " ".join(course_name.split())
        else:
            base = path.stem.replace("InfoEng_", "").replace("Fisa disciplinei_", "").replace("2025-2026_FisaDisciplina_EN_", "")
            course_name = base.replace("-", " ").replace("_", " ")

        # 2. Year & Semester
        semester = self._parse_semester(full_text, path.name)
        year_of_study = self._parse_year(full_text, semester)

        # 3. ECTS Credits
        ects = self._parse_ects(full_text)

        # 4. Course Type
        course_type = self._parse_course_type(full_text)

        # 5. Study Program
        prog_match = self._extract_field(r"1\.6\s*Programme\s*/\s*Qualification\s*(.+?)(?=\n\s*2\.|$)", full_text, re.DOTALL)
        study_program = " ".join(prog_match.split()) if prog_match else self.default_program

        # 6. Objectives (Section 6)
        obj_match = re.search(r"6\.\s*Objectives\s*(.+?)(?=7\.\s*Specific competencies|$)", full_text, re.DOTALL | re.IGNORECASE)
        objectives = self._clean_text(obj_match.group(1)) if obj_match else None

        # 7. Competencies (Section 7)
        comp_match = re.search(r"7\.\s*Specific competencies[^\n]*\s*(.+?)(?=8\.\s*Contents|$)", full_text, re.DOTALL | re.IGNORECASE)
        competencies = self._clean_text(comp_match.group(1)) if comp_match else None

        # 8. Lecture & Lab Topics (Section 8)
        lecture_topics = None
        lab_topics = None

        # 8.1 Course
        sec8_course = re.search(r"8\.1\s*Course\s*(.+?)(?=8\.2\s*Seminary|9\.\s*Corroborat|\Z)", full_text, re.DOTALL | re.IGNORECASE)
        if sec8_course:
            lecture_topics = self._clean_table_topic_lines(sec8_course.group(1))

        # 8.2 Seminary / Laboratory
        sec8_lab = re.search(r"8\.2\s*Seminary\s*/\s*Laboratory\s*(.+?)(?=9\.\s*Corroborat|10\.\s*Assessment|\Z)", full_text, re.DOTALL | re.IGNORECASE)
        if sec8_lab:
            lab_topics = self._clean_table_topic_lines(sec8_lab.group(1))

        # Description
        description = objectives.split("\n")[0] if objectives else f"Course on {course_name}"

        return CanonicalCourse(
            university_name=self.university_name,
            study_program=study_program,
            code=None,
            title=course_name,
            title_en=course_name,
            ects=ects,
            semester=semester,
            year_of_study=year_of_study,
            language="en",
            course_type=course_type,
            optional_package="Optional Track" if course_type == "optional" else None,
            description=description,
            objectives=objectives,
            topics_lecture=lecture_topics,
            topics_seminar_lab=lab_topics,
            competencies=competencies,
            raw_text=full_text
        )

    def parse_all(self, directory_path: str) -> List[CanonicalCourse]:
        """Parses all PDF syllabi in a given directory."""
        pdf_files = glob.glob(os.path.join(directory_path, "*.pdf"))
        print(f"📚 Found {len(pdf_files)} PDF files in {directory_path}...")

        courses: List[CanonicalCourse] = []
        for pdf_path in pdf_files:
            try:
                course = self.parse_pdf(pdf_path)
                courses.append(course)
                lec_count = len(course.topics_lecture.split('\n')) if course.topics_lecture else 0
                print(f"  ✓ [Sem {course.semester or '?'}] {course.title} ({course.ects} ECTS, {course.course_type}) - {lec_count} lecture topics")
            except Exception as e:
                print(f"  ✗ Error parsing {pdf_path}: {e}")

        return courses


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Parse university syllabi into CanonicalCourse JSON")
    parser.add_argument("--input-dir", default="data/raw_syllabi/uaic", help="Directory containing PDF syllabi")
    parser.add_argument("--output-json", default="data/processed/uaic_courses.json", help="Output JSON path")
    args = parser.parse_args()

    pdf_parser = UAICPDFParser(university_name="Universitatea Alexandru Ioan Cuza (UAIC)")
    courses = pdf_parser.parse_all(args.input_dir)

    os.makedirs(os.path.dirname(args.output_json), exist_ok=True)

    curriculum = CurriculumPackage(
        university_name="Universitatea Alexandru Ioan Cuza (UAIC)",
        study_program="Computer Science (in English)",
        academic_year="2025-2026",
        degree_cycle="bachelor",
        courses=courses
    )

    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(curriculum.model_dump(), f, ensure_ascii=False, indent=2)

    print(f"\n🎉 Successfully parsed {len(courses)} courses with rich topics and saved to {args.output_json}!")


if __name__ == "__main__":
    main()
