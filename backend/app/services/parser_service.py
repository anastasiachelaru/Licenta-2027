"""Parser Service for ErasmusMatch backend.

Wraps the syllabus extraction capabilities for use in backend pipelines
and API endpoints.
"""

from typing import List
from backend.app.models.canonical import CanonicalCourse, CurriculumPackage
from scripts.parser import UAICPDFParser


class SyllabusParserService:
    """Service to handle document ingestion for different university formats."""

    def __init__(self, university_name: str = "UAIC", default_program: str = "Computer Science"):
        self.parser = UAICPDFParser(university_name=university_name, default_program=default_program)

    def parse_single_pdf(self, file_path: str) -> CanonicalCourse:
        """Parse a single PDF syllabus."""
        return self.parser.parse_pdf(file_path)

    def parse_directory(self, directory_path: str) -> CurriculumPackage:
        """Parse an entire directory of syllabi into a CurriculumPackage."""
        courses = self.parser.parse_all(directory_path)
        return CurriculumPackage(
            university_name=self.parser.university_name,
            study_program=self.parser.default_program,
            academic_year="2025-2026",
            degree_cycle="bachelor",
            courses=courses
        )


parser_service = SyllabusParserService()

