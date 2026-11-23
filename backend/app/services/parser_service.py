"""Parser Service for ErasmusMatch backend.

Wraps syllabus extraction capabilities for multiple universities
(UAIC, UCM, EUC) for use in backend pipelines and API endpoints.
"""

from typing import List, Dict, Type
from backend.app.models.canonical import CanonicalCourse, CurriculumPackage
from scripts.parser import UAICPDFParser
from scripts.parser_ucm import UCMPDFParser
from scripts.parser_euc import EUCPDFParser


class SyllabusParserService:
    """Service to handle document ingestion for different university formats."""

    def __init__(self):
        self.parsers: Dict[str, any] = {
            "uaic": UAICPDFParser(),
            "ucm": UCMPDFParser(),
            "euc": EUCPDFParser()
        }

    def get_parser(self, uni_key: str):
        key = uni_key.lower().strip()
        if "ucm" in key or "madrid" in key or "complutense" in key:
            return self.parsers["ucm"]
        elif "euc" in key or "cyprus" in key:
            return self.parsers["euc"]
        return self.parsers["uaic"]

    def parse_single_pdf(self, file_path: str, uni_key: str = "uaic") -> CanonicalCourse:
        """Parse a single PDF syllabus using the corresponding university parser."""
        parser = self.get_parser(uni_key)
        return parser.parse_pdf(file_path)

    def parse_directory(self, directory_path: str, uni_key: str = "uaic") -> CurriculumPackage:
        """Parse an entire directory of syllabi into a CurriculumPackage."""
        parser = self.get_parser(uni_key)
        courses = parser.parse_all(directory_path)
        return CurriculumPackage(
            university_name=parser.university_name,
            study_program=getattr(parser, "default_program", getattr(parser, "study_program", "Computer Science")),
            academic_year="2023-2024",
            degree_cycle="bachelor",
            courses=courses
        )


parser_service = SyllabusParserService()
