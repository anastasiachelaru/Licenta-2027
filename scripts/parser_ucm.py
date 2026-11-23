"""Parser for Universidad Complutense de Madrid (UCM) Syllabi (PDF to CanonicalCourse).

Extracts structured curriculum data from UCM 'Ficha del curso' PDFs into the unified
CanonicalCourse schema (Pydantic).
"""

import os
import re
import glob
import json
from typing import List, Optional, Tuple
from pathlib import Path
import pdfplumber

from backend.app.models.canonical import CanonicalCourse, CurriculumPackage


class UCMPDFParser:
    """Extracts curriculum data from UCM (Facultad de Informática) course syllabus PDFs."""

    def __init__(
        self,
        university_name: str = "Universidad Complutense de Madrid (UCM)",
        study_program: str = "Grado en Ingeniería Informática"
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
        """Parses Year (1-4) and Semester (1-8) from UCM Curso string."""
        # Examples:
        # "Curso: 1º ( 1C )" -> Year 1, Sem 1
        # "Curso: 1º ( 2C )" -> Year 1, Sem 2
        # "Curso: 2º ( 1C )" -> Year 2, Sem 3
        # "Curso: 2º ( 2C )" -> Year 2, Sem 4
        # "Curso: 3º ( 1C )" -> Year 3, Sem 5
        # "Curso: Optativas generales 3º y 4º ( 2C )" -> Year 3/4, Sem 6
        first_page = text[:1500]

        # Extract cuatrimestre: 1C (Fall) or 2C (Spring)
        c_match = re.search(r"\(?\s*([12])\s*C\s*\)?", first_page, re.IGNORECASE)
        cuatrimestre = int(c_match.group(1)) if c_match else None

        # Extract year: 1º, 2º, 3º, 4º
        y_match = re.search(r"\b([1234])º\b", first_page)
        year = int(y_match.group(1)) if y_match else None

        if not year and "optativas" in first_page.lower():
            year = 3  # Most electives are 3rd/4th year

        semester = None
        if year and cuatrimestre:
            semester = (year - 1) * 2 + cuatrimestre
        elif year and not cuatrimestre:
            semester = (year - 1) * 2 + 1
        elif cuatrimestre and not year:
            semester = cuatrimestre

        return year, semester

    def _parse_language(self, text: str) -> str:
        match = re.search(r"Idioma:\s*([^\n]+)", text[:1200], re.IGNORECASE)
        if match:
            lang_str = match.group(1).lower()
            if "inglés" in lang_str or "ingles" in lang_str or "english" in lang_str:
                return "en"
        return "es"

    def _parse_course_type(self, text: str) -> str:
        match = re.search(r"Car[aá]cter:\s*([^\n]+)", text[:1200], re.IGNORECASE)
        if match:
            c_type = match.group(1).lower()
            if "optativa" in c_type:
                return "optional"
            elif "obligatoria" in c_type or "básica" in c_type or "basica" in c_type:
                return "mandatory"
        return "mandatory"

    def _parse_ects(self, text: str) -> float:
        # Match "6 ECTS" or "6,0 ECTS" near course header
        match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*ECTS\b", text[:1200], re.IGNORECASE)
        if match:
            val = match.group(1).replace(",", ".")
            try:
                return float(val)
            except ValueError:
                pass
        return 6.0

    def parse_pdf(self, file_path: str) -> CanonicalCourse:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        full_pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                full_pages.append(page.extract_text() or "")

        full_text = "\n".join(full_pages)

        # 1. Course Code and Title
        asig_match = re.search(
            r"Asignatura:\s*(?:(\d{5,7})\s*-?\s*)?([^\n]+?)(?:\s+Abrev:|\s+\d+\s*ECTS|$)",
            full_text,
            re.IGNORECASE
        )
        if asig_match:
            code = asig_match.group(1) or path.stem
            title = asig_match.group(2).strip()
        else:
            code = path.stem
            title = path.stem

        # Clean title
        title = re.sub(r"\s+", " ", title).strip()

        # 2. English Title if present
        title_en_match = re.search(
            r"Asignatura en Ingl[eé]s:\s*(.+?)(?=\s*Car[aá]cter:|\n|$)",
            full_text,
            re.IGNORECASE
        )
        title_en = title_en_match.group(1).strip() if title_en_match else title

        # 3. Year & Semester
        year, semester = self._parse_year_and_semester(full_text)

        # 4. ECTS Credits
        ects = self._parse_ects(full_text)

        # 5. Language
        language = self._parse_language(full_text)

        # 6. Course Type
        course_type = self._parse_course_type(full_text)

        # 7. Objectives / Minimal Contents (Descripción de contenidos mínimos)
        desc_match = re.search(
            r"Descripción de contenidos mínimos:\s*(.+?)(?=Programa detallado:|Resultados de aprendizaje:|Competencias|Evaluación|Actividades|Bibliografía|$)",
            full_text,
            re.DOTALL | re.IGNORECASE
        )
        description = self._clean_text(desc_match.group(1)) if desc_match else None

        # 8. Lecture Topics (Programa detallado)
        prog_match = re.search(
            r"Programa detallado:\s*(.+?)(?=Programa detallado en inglés:|Resultados de aprendizaje:|Competencias de la asignatura:|Evaluación|Actividades|Bibliografía|$)",
            full_text,
            re.DOTALL | re.IGNORECASE
        )
        lecture_topics = self._clean_text(prog_match.group(1)) if prog_match else None

        # If there is also an English detailed program, we can capture it
        prog_en_match = re.search(
            r"Programa detallado en inglés:\s*(.+?)(?=Resultados de aprendizaje:|Competencias de la asignatura:|Evaluación|Actividades|Bibliografía|$)",
            full_text,
            re.DOTALL | re.IGNORECASE
        )
        if prog_en_match:
            en_prog = self._clean_text(prog_en_match.group(1))
            if en_prog and len(en_prog) > 20:
                if lecture_topics:
                    lecture_topics = f"{lecture_topics}\n\n[English Syllabus Summary]:\n{en_prog}"
                else:
                    lecture_topics = en_prog

        # 9. Competencies / Learning Outcomes (Resultados de aprendizaje / Competencias)
        res_match = re.search(
            r"Resultados de aprendizaje:\s*(.+?)(?=Evaluación detallada|Evaluación|Actividades|Bibliografía|$)",
            full_text,
            re.DOTALL | re.IGNORECASE
        )
        comp_match = re.search(
            r"Competencias de la asignatura:\s*(.+?)(?=Evaluación|Actividades|Bibliografía|$)",
            full_text,
            re.DOTALL | re.IGNORECASE
        )
        competencies_parts = []
        if res_match:
            res_txt = self._clean_text(res_match.group(1))
            if res_txt:
                competencies_parts.append(f"Resultados de aprendizaje:\n{res_txt}")
        if comp_match:
            comp_txt = self._clean_text(comp_match.group(1))
            if comp_txt:
                competencies_parts.append(f"Competencias:\n{comp_txt}")

        competencies = "\n\n".join(competencies_parts) if competencies_parts else None

        # 10. Lab Topics / Practical hours
        lab_match = re.search(
            r"Laboratorios:\s*([0-9.,]+)",
            full_text,
            re.IGNORECASE
        )
        lab_topics = None
        if lab_match:
            lab_hours = lab_match.group(1)
            lab_topics = f"Créditos de Laboratorio / Prácticas: {lab_hours} ECTS"

        # Build objectives from description or initial section
        objectives = description if description else f"Asignatura sobre {title}"

        return CanonicalCourse(
            university_name=self.university_name,
            study_program=self.study_program,
            code=code,
            title=title,
            title_en=title_en,
            ects=ects,
            semester=semester,
            year_of_study=year,
            language=language,
            course_type=course_type,
            optional_package="Módulo Optativo" if course_type == "optional" else None,
            description=description,
            objectives=objectives,
            topics_lecture=lecture_topics,
            topics_seminar_lab=lab_topics,
            competencies=competencies,
            raw_text=full_text
        )

    def parse_all(self, directory_path: str) -> List[CanonicalCourse]:
        pdf_files = glob.glob(os.path.join(directory_path, "*.pdf"))
        print(f"📚 Found {len(pdf_files)} UCM PDF files in {directory_path}...")

        courses: List[CanonicalCourse] = []
        for pdf_path in pdf_files:
            try:
                course = self.parse_pdf(pdf_path)
                courses.append(course)
                print(f"  ✓ [{course.code}] {course.title} ({course.ects} ECTS, Sem {course.semester}, {course.language})")
            except Exception as e:
                print(f"  ✗ Error parsing {pdf_path}: {e}")

        return courses


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Parse UCM syllabi into CanonicalCourse JSON")
    parser.add_argument("--input-dir", default="data/raw_syllabi/ucm", help="Directory containing UCM PDF syllabi")
    parser.add_argument("--output-json", default="data/processed/ucm_courses.json", help="Output JSON path")
    args = parser.parse_args()

    ucm_parser = UCMPDFParser()
    courses = ucm_parser.parse_all(args.input_dir)

    os.makedirs(os.path.dirname(args.output_json), exist_ok=True)

    curriculum = CurriculumPackage(
        university_name=ucm_parser.university_name,
        study_program=ucm_parser.study_program,
        academic_year="2023-2024",
        degree_cycle="bachelor",
        courses=courses
    )

    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(curriculum.model_dump(), f, ensure_ascii=False, indent=2)

    print(f"\n🎉 Successfully parsed {len(courses)} UCM courses and saved to {args.output_json}!")


if __name__ == "__main__":
    main()
