"""Canonical Course Data Model for ErasmusMatch.

Agnostic representation of an academic course syllabus across different
universities, languages, and curriculum formats.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class CanonicalCourse(BaseModel):
    """Unified schema representing a course extracted from any university syllabus."""

    university_name: str = Field(..., description="Name of the university (e.g., UAIC)")
    study_program: str = Field(default="Computer Science", description="Study program name")
    code: Optional[str] = Field(None, description="Official course code, e.g., CS1101")
    title: str = Field(..., description="Original course title")
    title_en: Optional[str] = Field(None, description="English translation of course title if available")
    ects: float = Field(..., ge=0.0, description="ECTS credit points, usually 4.0 - 6.0")
    semester: Optional[int] = Field(None, ge=1, le=12, description="Semester number (1-6 for Bachelor)")
    year_of_study: Optional[int] = Field(None, ge=1, le=6, description="Year of study (1-3 for Bachelor)")
    language: str = Field(default="en", description="Instruction language: 'en', 'ro', 'es', etc.")
    course_type: str = Field(default="mandatory", description="'mandatory', 'optional', 'elective'")
    optional_package: Optional[str] = Field(None, description="Optional package identifier, e.g., 'Package 1'")

    # Detailed syllabus contents
    description: Optional[str] = Field(None, description="General course overview")
    objectives: Optional[str] = Field(None, description="General and specific learning objectives")
    topics_lecture: Optional[str] = Field(None, description="Weekly or topical lecture content breakdown")
    topics_seminar_lab: Optional[str] = Field(None, description="Practical laboratory / seminar topics")
    competencies: Optional[str] = Field(None, description="Professional and transversal competencies acquired")
    raw_text: Optional[str] = Field(None, description="Cleaned full extracted raw text from syllabus")

    def to_embedding_text(self) -> str:
        """Constructs a dense, semantically rich string for multilingual vector embedding.

        Balances title importance with core topics, objectives, and competencies.
        """
        parts: List[str] = []
        
        # Title is given prominent weight by placing it first
        parts.append(f"Course: {self.title}")
        if self.title_en and self.title_en != self.title:
            parts.append(f"English Title: {self.title_en}")

        if self.objectives:
            parts.append(f"Objectives: {self.objectives.strip()}")

        if self.topics_lecture:
            parts.append(f"Lecture Topics: {self.topics_lecture.strip()}")

        if self.topics_seminar_lab:
            parts.append(f"Lab & Practice: {self.topics_seminar_lab.strip()}")

        if self.competencies:
            parts.append(f"Competencies: {self.competencies.strip()}")

        # Fallback if specific sections were missing
        if len(parts) == 1 and self.raw_text:
            cleaned = " ".join(self.raw_text.split()[:400])
            parts.append(f"Content: {cleaned}")

        return "\n".join(parts)


class CurriculumPackage(BaseModel):
    """A collection of courses representing a semester or degree curriculum."""
    university_name: str
    study_program: str
    academic_year: Optional[str] = None
    degree_cycle: str = "bachelor"
    courses: List[CanonicalCourse] = []

