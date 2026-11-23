"""Parser for European University Cyprus (EUC) Syllabi (PDF to CanonicalCourse).

Extracts structured curriculum data from EUC course syllabus PDFs into the unified
CanonicalCourse schema (Pydantic).
"""

import os
import re
import glob
import json
from typing import List, Optional, Tuple, Dict
from pathlib import Path
import pdfplumber

from backend.app.models.canonical import CanonicalCourse, CurriculumPackage


class EUCPDFParser:
    """Extracts curriculum data from European University Cyprus syllabus PDFs."""

    def __init__(
        self,
        university_name: str = "European University Cyprus (EUC)",
        study_program: str = "Computer Science"
    ):
        self.university_name = university_name
        self.study_program = study_program

    def _clean_text(self, text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        text = text.replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _parse_year_and_semester(self, text: str) -> Tuple[Optional[int], Optional[int]]:
        """Parses Year and Semester from EUC text (handles '1st Year / 1st Semester', '4th Year / 7th or 8th', etc.)."""
        m = re.search(r"(\d+)(?:st|nd|rd|th)?\s*Year\s*/\s*(\d+)", text, re.IGNORECASE)
        if m:
            year = int(m.group(1))
            sem_raw = int(m.group(2))
            if sem_raw in (1, 2) and year > 1:
                semester = (year - 1) * 2 + sem_raw
            else:
                semester = sem_raw
            return year, semester

        y_m = re.search(r"(\d+)(?:st|nd|rd|th)?\s*Year", text, re.IGNORECASE)
        s_m = re.search(r"(\d+)(?:st|nd|rd|th)?\s*Semester", text, re.IGNORECASE)
        year = int(y_m.group(1)) if y_m else None
        sem = int(s_m.group(1)) if s_m else None
        if year and sem and sem in (1, 2) and year > 1:
            sem = (year - 1) * 2 + sem
        return year, sem

    def _parse_course_type(self, type_str: str) -> str:
        # Check BCSC (Bachelor in Computer Science) first
        bcsc_m = re.search(r"BCSC\s*:\s*([A-Za-z]+)", type_str, re.IGNORECASE)
        if bcsc_m:
            val = bcsc_m.group(1).lower()
            if "elective" in val or "optional" in val:
                return "optional"
            elif "compulsory" in val or "mandatory" in val:
                return "mandatory"

        # General fallback
        lower = type_str.lower()
        if "elective" in lower or "optional" in lower:
            return "optional"
        return "mandatory"

    def _parse_ects(self, ects_str: str) -> float:
        m = re.search(r"(\d+(?:[.,]\d+)?)", ects_str)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                pass
        return 6.0

    def parse_pdf(self, file_path: str) -> CanonicalCourse:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        full_pages = []
        table_cells: Dict[str, str] = {}

        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                full_pages.append(page.extract_text() or "")
                tables = page.extract_tables() or []
                for t in tables:
                    for row in t:
                        non_empty = [c.strip() for c in row if c and c.strip()]
                        if len(non_empty) >= 2:
                            k = non_empty[0].replace("\n", " ").strip().lower()
                            v = non_empty[-1].strip()
                            if k not in table_cells or len(v) > len(table_cells[k]):
                                table_cells[k] = v

        full_text = "\n".join(full_pages)

        # 1. Course Code (prefer filename or table)
        code = path.stem
        for k, v in table_cells.items():
            if "course code" in k:
                cleaned_code = v.split()[0].strip()
                if len(cleaned_code) >= 4:
                    code = cleaned_code
                    break

        # 2. Course Title
        title = None
        for k, v in table_cells.items():
            if "course title" in k:
                title = v.replace("\n", " ").strip()
                break

        if not title:
            # Fallback to regex on text
            t_m = re.search(r"Course Title\s*[:\s]\s*([^\n]+)", full_text, re.IGNORECASE)
            title = t_m.group(1).strip() if t_m else code

        # 3. Year & Semester
        year, semester = self._parse_year_and_semester(full_text)
        if semester and not year:
            year = (semester + 1) // 2

        # 4. ECTS Credits
        e_m = re.search(r"\bECTS\b[^\d\n]*(\d+(?:[.,]\d+)?)", full_text, re.IGNORECASE)
        ects = float(e_m.group(1).replace(",", ".")) if e_m else 6.0

        # 5. Course Type
        course_type = "mandatory"
        for k, v in table_cells.items():
            if "course type" in k:
                course_type = self._parse_course_type(v)
                break

        # 6. Objectives (Course Purpose and Objectives)
        objectives = None
        for k, v in table_cells.items():
            if "purpose" in k or "objectives" in k:
                objectives = self._clean_text(v)
                break
        if not objectives:
            obj_m = re.search(
                r"Course Purpose\s*(?:and Objectives)?\s*(.+?)(?=Learning\s*Outcomes|Course Content|Prerequisites|Teaching|$)",
                full_text,
                re.DOTALL | re.IGNORECASE
            )
            objectives = self._clean_text(obj_m.group(1)) if obj_m else f"Course on {title}"

        # 7. Competencies (Learning Outcomes)
        competencies = None
        for k, v in table_cells.items():
            if "learning outcomes" in k or "outcomes" in k:
                competencies = self._clean_text(v)
                break
        if not competencies:
            lo_m = re.search(
                r"Learning\s*Outcomes\s*(.+?)(?=Course Content|Prerequisites|Co-requisites|Teaching Methodology|Bibliography|$)",
                full_text,
                re.DOTALL | re.IGNORECASE
            )
            competencies = self._clean_text(lo_m.group(1)) if lo_m else None

        # 8. Lecture Topics (Course Content)
        lecture_topics = None
        for k, v in table_cells.items():
            if "course content" in k or k == "content":
                lecture_topics = self._clean_text(v)
                break
        if not lecture_topics:
            cc_m = re.search(
                r"Course Content\s*(.+?)(?=Teaching\s*Methodology|Teaching|Bibliography|Assessment|Language|$)",
                full_text,
                re.DOTALL | re.IGNORECASE
            )
            lecture_topics = self._clean_text(cc_m.group(1)) if cc_m else None

        # 9. Lab Topics / Practical load (Teaching Methodology)
        lab_topics = None
        for k, v in table_cells.items():
            if "teaching" in k and "methodology" in k:
                # Extract practical load line
                prac_m = re.search(r"(?:Recommended practical load|practical load)\s*:\s*(.+?)(?=\n\n|$)", v, re.DOTALL | re.IGNORECASE)
                if prac_m:
                    lab_topics = self._clean_text(prac_m.group(1))
                else:
                    lab_topics = self._clean_text(v[:300])
                break

        # Fallback description
        description = objectives.split("\n")[0] if objectives else f"Course {code} - {title}"

        return CanonicalCourse(
            university_name=self.university_name,
            study_program=self.study_program,
            code=code,
            title=title,
            title_en=title,
            ects=ects,
            semester=semester,
            year_of_study=year,
            language="en",
            course_type=course_type,
            optional_package="Elective Track" if course_type == "optional" else None,
            description=description,
            objectives=objectives,
            topics_lecture=lecture_topics,
            topics_seminar_lab=lab_topics,
            competencies=competencies,
            raw_text=full_text
        )

    def parse_all(self, directory_path: str) -> List[CanonicalCourse]:
        pdf_files = glob.glob(os.path.join(directory_path, "*.pdf"))
        print(f"📚 Found {len(pdf_files)} EUC PDF files in {directory_path}...")

        courses: List[CanonicalCourse] = []
        for pdf_path in pdf_files:
            try:
                course = self.parse_pdf(pdf_path)
                courses.append(course)
                print(f"  ✓ [{course.code}] {course.title} ({course.ects} ECTS, Sem {course.semester}, {course.course_type})")
            except Exception as e:
                print(f"  ✗ Error parsing {pdf_path}: {e}")

        return courses


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Parse EUC syllabi into CanonicalCourse JSON")
    parser.add_argument("--input-dir", default="data/raw_syllabi/euc", help="Directory containing EUC PDF syllabi")
    parser.add_argument("--output-json", default="data/processed/euc_courses.json", help="Output JSON path")
    args = parser.parse_args()

    euc_parser = EUCPDFParser()
    courses = euc_parser.parse_all(args.input_dir)

    os.makedirs(os.path.dirname(args.output_json), exist_ok=True)

    curriculum = CurriculumPackage(
        university_name=euc_parser.university_name,
        study_program=euc_parser.study_program,
        academic_year="2023-2024",
        degree_cycle="bachelor",
        courses=courses
    )

    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(curriculum.model_dump(), f, ensure_ascii=False, indent=2)

    print(f"\n🎉 Successfully parsed {len(courses)} EUC courses and saved to {args.output_json}!")


if __name__ == "__main__":
    main()
