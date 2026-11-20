"""SQLAlchemy database models for ErasmusMatch with pgvector support."""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, String, Text, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from backend.app.db.session import Base
from backend.app.core.config import settings


class University(Base):
    __tablename__ = "universities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    country = Column(String(100), nullable=False)
    city = Column(String(100), nullable=True)
    erasmus_code = Column(String(50), nullable=True, unique=True, index=True)
    website = Column(String(255), nullable=True)

    programs = relationship("StudyProgram", back_populates="university", cascade="all, delete-orphan")


class StudyProgram(Base):
    __tablename__ = "study_programs"

    id = Column(Integer, primary_key=True, index=True)
    university_id = Column(Integer, ForeignKey("universities.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    degree_cycle = Column(String(50), default="bachelor")  # bachelor, master
    academic_year = Column(String(20), nullable=True)      # e.g., 2025-2026

    university = relationship("University", back_populates="programs")
    courses = relationship("Course", back_populates="program", cascade="all, delete-orphan")


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    program_id = Column(Integer, ForeignKey("study_programs.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(50), nullable=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    title_en = Column(String(255), nullable=True)
    ects = Column(Float, nullable=False, default=5.0)
    semester = Column(Integer, nullable=True)              # 1 to 6
    year_of_study = Column(Integer, nullable=True)         # 1 to 3
    language = Column(String(10), default="en")            # en, ro, es, it, fr, etc.
    course_type = Column(String(50), default="mandatory")  # mandatory, optional, elective
    optional_package = Column(String(100), nullable=True)  # e.g., 'Package 1', 'Elective Track A'

    # Syllabus Details
    description = Column(Text, nullable=True)
    objectives = Column(Text, nullable=True)
    topics_lecture = Column(Text, nullable=True)
    topics_seminar_lab = Column(Text, nullable=True)
    competencies = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True)

    program = relationship("StudyProgram", back_populates="courses")
    embedding = relationship("CourseEmbedding", back_populates="course", uselist=False, cascade="all, delete-orphan")


class CourseEmbedding(Base):
    __tablename__ = "course_embeddings"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    text_representation = Column(Text, nullable=False)
    embedding = Column(Vector(settings.EMBEDDING_DIMENSION), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    course = relationship("Course", back_populates="embedding")
