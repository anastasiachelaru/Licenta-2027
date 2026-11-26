"""Universal Syllabus Parser Service for ErasmusMatch.

Agnostic, 100% university-independent two-stage hybrid parsing architecture
(Chain of Responsibility / Strategy pattern) that transforms syllabus PDFs from
any university into canonical CanonicalCourse models.

Stage 1: UniversalBolognaParser (multilingual heuristics covering Bologna / ECTS standards)
Quality Gate: _is_extraction_valid (validates title, positive ECTS, substantive content)
Stage 2: LLMFallbackExtractor (structured LLM extraction or graceful offline raw fallback)
Orchestrator: HybridSyllabusParser
"""

import os
import re
import json
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pdfplumber

from backend.app.models.canonical import CanonicalCourse, CurriculumPackage

logger = logging.getLogger(__name__)

LANGUAGE_STOPWORDS: Dict[str, List[str]] = {
    "en": ["the", "and", "of", "to", "in", "course", "learning", "students", "assessment", "hours", "credits", "lecture"],
    "es": ["de", "en", "el", "la", "los", "las", "curso", "créditos", "creditos", "asignatura", "aprendizaje", "evaluación"],
    "ro": ["și", "si", "de", "la", "în", "in", "curs", "credite", "disciplina", "disciplinei", "evaluare", "ore"],
    "de": ["und", "der", "die", "das", "von", "kurs", "leistungspunkte", "modul", "prüfung", "semester", "lehrveranstaltung"],
    "fr": ["de", "et", "le", "la", "les", "des", "cours", "crédits", "évaluation", "apprentissage", "matière"],
    "it": ["di", "del", "della", "e", "il", "corso", "crediti", "insegnamento", "esame", "obiettivi"],
    "pt": ["de", "da", "do", "para", "em", "curso", "créditos", "disciplina", "avaliação", "estudantes"],
}

ROMAN_TO_INT: Dict[str, int] = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6,
    "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12,
}


class UniversalBolognaParser:
    """Stage 1: Universal, university-agnostic heuristic parser for European & Bologna syllabi.
    
    Operates without hardcoded university rules, using standard academic anchors
    across multiple European languages (EN, ES, RO, DE, FR, IT, PT).
    """

    def detect_language(self, text: str) -> str:
        """Detects document language based on academic vocabulary and stopword frequencies."""
        words = re.findall(r"\b[a-zăâîșțáéíóúüñßàèìòù]{2,}\b", text.lower())
        if not words:
            return "en"
        word_set = set(words)
        scores: Dict[str, int] = {}
        for lang, markers in LANGUAGE_STOPWORDS.items():
            scores[lang] = sum(1 for m in markers if m in word_set)
        best_lang = max(scores, key=scores.get)
        return best_lang if scores[best_lang] > 1 else "en"

    def _clean_noise_and_bibliography(self, section_text: str) -> str:
        """Strips bibliography, table formatting noise, and teaching method boilerplate."""
        if not section_text:
            return ""

        # Standalone bibliography heading cut-off (cross-language)
        bib_pat = (
            r"\n\s*(?:Bibliography|Bibliograf[ií]a|Bibliografie|Bibliographie|"
            r"Literatur|Riferimenti bibliografici|References|Referin[tț]e)\s*[:\n]"
        )
        cut = re.split(bib_pat, section_text, flags=re.IGNORECASE)[0]

        boilerplate_patterns = [
            "teaching methods", "remarks", "number oh hours", "references)",
            "course programme", "access to additional resources", "course website",
            "laboratory website", "fisa disciplinei", "ficha del curso"
        ]

        method_indicators = (
            r"\s*(?:Interactive presentations|Slides|blackboard|Online access|Direct interaction|"
            r"Lecturing|Slide presentation|Problem-based learning|Exercise|Conversational|"
            r"Heuristic conversation|Case study|Demonstration|Debate|Project-based).*$"
        )

        cleaned_lines = []
        for line in cut.split("\n"):
            line_str = line.strip()
            if not line_str:
                continue
            if any(b in line_str.lower() for b in boilerplate_patterns):
                continue
            line_str = re.sub(method_indicators, "", line_str, flags=re.IGNORECASE)
            line_str = re.sub(r"\s*\d+\s*(?:,\s*see\b|\bhours?\b|\bore\b).*$", "", line_str, flags=re.IGNORECASE)
            line_str = re.sub(r"\s*see bibliography.*$", "", line_str, flags=re.IGNORECASE)
            line_str = line_str.strip()
            if len(line_str) > 3 and not line_str.lower().endswith("see"):
                if not cleaned_lines or cleaned_lines[-1] != line_str:
                    cleaned_lines.append(line_str)

        return "\n".join(cleaned_lines).strip()

    def _extract_tables_and_text(self, path: Path) -> Tuple[str, Dict[str, str]]:
        """Extracts text and flattened key-value table structures from PDF."""
        full_pages = []
        table_cells: Dict[str, str] = {}
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                full_pages.append(page.extract_text() or "")
                tables = page.extract_tables() or []
                for t in tables:
                    for row in t:
                        if not row:
                            continue
                        non_empty = [c.strip() for c in row if c and c.strip()]
                        if len(non_empty) >= 2:
                            k = non_empty[0].replace("\n", " ").strip().lower()
                            v = non_empty[-1].strip()
                            if k not in table_cells or len(v) > len(table_cells[k]):
                                table_cells[k] = v
        return "\n".join(full_pages), table_cells

    def parse(self, file_path: str, university_name: Optional[str] = None) -> CanonicalCourse:
        """Parses a syllabus PDF into a CanonicalCourse model using universal Bologna heuristics."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Syllabus file not found: {file_path}")

        full_text, table_cells = self._extract_tables_and_text(path)
        first_page = full_text[:3000]

        # 1. University Name (generic detection if not explicitly passed)
        detected_uni = university_name
        if not detected_uni:
            uni_m = re.search(
                r"(?:University|Universidad|Universitatea|Université|Universität|Università)\s*[:.\s\"“]?\s*([^\n\"”\r]+)",
                first_page,
                re.IGNORECASE
            )
            if uni_m:
                clean_uni = uni_m.group(0).strip(" \"'“”,.:")
                # Avoid trivial fragments like 'University University'
                if len(clean_uni) > 12:
                    detected_uni = clean_uni
                else:
                    detected_uni = path.parent.name.upper()
            else:
                detected_uni = path.parent.name.upper()

        # 2. Study Program
        study_program = "Computer Science"
        prog_m = re.search(
            r"(?:1\.6\s*Programme\s*/\s*Qualification|Grado|Program de studii|Degree|Studiengang|Filière)\s*[:.\s-]?\s*([^\n]+)",
            first_page,
            re.IGNORECASE
        )
        if prog_m:
            cand = prog_m.group(1).strip()
            if len(cand) > 3 and not cand.lower().startswith("licence"):
                study_program = " ".join(cand.split())

        # 3. Course Code
        code = None
        for k, v in table_cells.items():
            if any(c_kw in k for c_kw in ["course code", "code", "código", "codul disciplinei", "codice"]):
                clean_code = v.split()[0].strip()
                if len(clean_code) >= 3:
                    code = clean_code
                    break
        if not code:
            code_m = re.search(
                r"(?:Course Code|C[oó]digo|Codul disciplinei)\s*[:.\s-]\s*([A-Za-z0-9_\-\.\/]+)",
                first_page,
                re.IGNORECASE
            )
            if code_m:
                code = code_m.group(1).strip()
        if not code:
            asig_code = re.search(r"Asignatura:\s*(\d{5,7})\b", first_page, re.IGNORECASE)
            if asig_code:
                code = asig_code.group(1).strip()
        if not code:
            code = path.stem

        # 4. Course Title
        title = None
        for k, v in table_cells.items():
            if any(t_kw in k for t_kw in ["course title", "course name", "denumirea disciplinei", "titlu curs", "lehrveranstaltung", "intitulé"]):
                title = v.replace("\n", " ").strip()
                break
        if not title:
            t_num_match = re.search(
                r"(?:2\.1\s*Course Name|Course Name|Course Title|Denumirea disciplinei|Titlul disciplinei)\s*[:.\s-]?\s*([^\n]+?)(?=\n\s*(?:2\.2|Course taught|Teacher|$))",
                first_page,
                re.IGNORECASE
            )
            if t_num_match:
                title = t_num_match.group(1).strip()
        if not title:
            t_asig_match = re.search(
                r"Asignatura:\s*(?:\d{5,7}\s*-?\s*)?([^\n]+?)(?:\s+Abrev:|\s+\d+\s*ECTS|\n|$)",
                first_page,
                re.IGNORECASE
            )
            if t_asig_match:
                title = t_asig_match.group(1).strip()
        if not title:
            base = path.stem
            base = re.sub(r"^(?:20\d\d-20\d\d_)?(?:FisaDisciplina|Fisa disciplinei|Ficha)_[A-Z]{2}_?", "", base, flags=re.IGNORECASE)
            title = base.replace("-", " ").replace("_", " ").strip()

        title = re.sub(r"\s+", " ", title).strip()

        # English Title if present
        title_en = None
        t_en_m = re.search(
            r"(?:Asignatura en Ingl[eé]s|English Title|Course Title \(EN\))\s*[:.\s-]?\s*(.+?)(?=\s*Car[aá]cter:|\n|$)",
            first_page,
            re.IGNORECASE
        )
        if t_en_m:
            title_en = t_en_m.group(1).strip()
        else:
            title_en = title

        # 5. ECTS Credits
        ects = None
        # Priority 1: Label followed by numeric value
        e_m1 = re.search(
            r"(?:Credit points?|Num[aă]r(?:ul)? de credite|Credite|ECTS|Cr[eé]ditos?|Credits?|CFU|LP|Leistungspunkte)\s*[:.\s-]?\s*(\d+(?:[.,]\d+)?)",
            first_page,
            re.IGNORECASE
        )
        if e_m1:
            val = float(e_m1.group(1).replace(",", "."))
            if 1.0 <= val <= 60.0:
                ects = val

        if not ects:
            # Priority 2: Numeric value followed by label (avoiding preceding dot like section numbers 3.9)
            e_m2 = re.search(
                r"(?<!\b\d\.)(\b[1-9]\d*(?:[.,]\d+)?)\s*(?:ECTS|Cr[eé]ditos?|Credits?|Credite|CFU|LP)\b",
                first_page,
                re.IGNORECASE
            )
            if e_m2:
                val = float(e_m2.group(1).replace(",", "."))
                if 1.0 <= val <= 60.0:
                    ects = val

        if not ects:
            for k, v in table_cells.items():
                if any(ek in k for ek in ["ects", "credits", "credite", "créditos", "credit points"]):
                    e_val = re.search(r"^(\d+(?:[.,]\d+)?)", v.strip())
                    if e_val:
                        try:
                            val = float(e_val.group(1).replace(",", "."))
                            if 1.0 <= val <= 60.0:
                                ects = val
                                break
                        except ValueError:
                            pass

        if not ects or ects <= 0.0 or ects > 60.0:
            ects = 6.0

        # 6. Year & Semester
        semester = None
        sem_m = re.search(
            r"(?:2\.5\s*Semester|Semester|Semestrul|Semestre)\s*[:.\s/]*([IVX]+|\d+)",
            first_page,
            re.IGNORECASE
        )
        if sem_m:
            raw_sem = sem_m.group(1).upper()
            semester = ROMAN_TO_INT.get(raw_sem, int(raw_sem) if raw_sem.isdigit() else None)

        cuatrimestre = None
        c_m = re.search(r"\(?\s*([12])\s*C\s*\)?", first_page, re.IGNORECASE)
        if c_m:
            cuatrimestre = int(c_m.group(1))

        year = None
        y_m = re.search(
            r"(?:2\.4\s*Year|Year|Anul|A[nñ]o|Année|Studienjahr)\s*[:.\s/]*([IVX]+|\d+)(?:st|nd|rd|th|º)?",
            first_page,
            re.IGNORECASE
        )
        if y_m:
            raw_y = y_m.group(1).upper()
            year = ROMAN_TO_INT.get(raw_y, int(raw_y) if raw_y.isdigit() else None)
        else:
            y_ord = re.search(r"\b([123456])º\b", first_page)
            if y_ord:
                year = int(y_ord.group(1))

        if year and cuatrimestre:
            semester = (year - 1) * 2 + cuatrimestre
        elif year and semester and semester in (1, 2) and year > 1:
            semester = (year - 1) * 2 + semester
        elif semester and not year:
            year = (semester + 1) // 2
        elif year and not semester:
            semester = (year - 1) * 2 + 1

        # 7. Language
        lang_m = re.search(r"(?:Idioma|Language|Limba de predare|Langue)\s*[:.\s-]?\s*([^\n]+)", first_page, re.IGNORECASE)
        if lang_m:
            l_str = lang_m.group(1).lower()
            if "ingl" in l_str or "engl" in l_str:
                language = "en"
            elif "span" in l_str or "español" in l_str:
                language = "es"
            elif "rom" in l_str:
                language = "ro"
            else:
                language = self.detect_language(full_text[:3000])
        else:
            language = self.detect_language(full_text[:3000])

        # 8. Course Type
        course_type = "mandatory"
        for k, v in table_cells.items():
            if any(ct_kw in k for ct_kw in ["course type", "carácter", "caracter", "tip curs", "tipul disciplinei"]):
                v_lower = v.lower()
                if any(opt in v_lower for opt in ["opt", "elect"]):
                    course_type = "optional"
                elif any(mand in v_lower for mand in ["mand", "compuls", "oblig", "básic", "basic"]):
                    course_type = "mandatory"
                break
        if course_type == "mandatory":
            ct_m = re.search(r"(?:Course type\**|Car[aá]cter|Tipul disciplinei)\s*[:.\s-]?\s*([^\n]+)", first_page, re.IGNORECASE)
            if ct_m:
                ct_val = ct_m.group(1).lower()
                if any(opt in ct_val for opt in ["opt", "elect"]):
                    course_type = "optional"

        # 9. Sections Extraction
        # Objectives
        objectives = None
        for k, v in table_cells.items():
            if any(okw in k for okw in ["course purpose", "learning objectives", "objectives", "obiective", "objetivos docentes"]):
                cand = self._clean_noise_and_bibliography(v)
                if len(cand) >= 40:
                    objectives = cand
                    break
        if not objectives:
            obj_m = re.search(
                r"(?:^|\n)\s*(?:6\.\s*Objectives|Course Purpose(?:\s*and Objectives)?|Objectives of the Course|Course Objectives?|Objetivos|Obiectivele disciplinei|Descripci[oó]n de contenidos m[ií]nimos)\s*[:.\n-]?\s*(.+?)(?=(?:^|\n)\s*(?:7\.\s*Specific|Learning Outcomes|Programa detallado|Competencias|Course Content|Contents|Evaluaci|Assessment|Bibliography|\Z))",
                full_text,
                re.DOTALL | re.IGNORECASE
            )
            if obj_m:
                objectives = self._clean_noise_and_bibliography(obj_m.group(1))

        # Lecture Topics
        lecture_topics = None
        for k, v in table_cells.items():
            if (k in ["course content", "syllabus", "content", "lecture topics", "programa analitica"] or
                ("course content" in k and "method" not in k and "program" not in k)):
                cand = self._clean_noise_and_bibliography(v)
                if len(cand) >= 50:
                    lecture_topics = cand
                    break

        if not lecture_topics:
            topic_m = re.search(
                r"(?:^|\n)\s*(?:8\.1\s*Course|Programa detallado|Course Content|Detailed Program|Tematic[aă] cursurilor|Syllabus|Contenuti del corso)\s*[:.\n-]?\s*(.+?)(?=(?:^|\n)\s*(?:8\.2\s*Seminary|Programa detallado en inglés|Resultados de aprendizaje|Competencias|Laboratorios?|Pr[aá]cticas|Teaching Methodology|Assessment|Evaluare|Evaluaci|9\.\s*Corroborat|10\.\s*Assessment|\Z))",
                full_text,
                re.DOTALL | re.IGNORECASE
            )
            if topic_m:
                lecture_topics = self._clean_noise_and_bibliography(topic_m.group(1))

        # Competencies
        competencies = None
        for k, v in table_cells.items():
            if any(ckw in k for ckw in ["learning outcomes", "competencies", "competences", "competencias", "competențe"]):
                cand = self._clean_noise_and_bibliography(v)
                if len(cand) >= 40:
                    competencies = cand
                    break
        if not competencies:
            comp_m = re.search(
                r"(?:^|\n)\s*(?:7\.\s*Specific competencies[^\n]*|Learning Outcomes|Resultados de aprendizaje|Competencias de la asignatura|Competencias|Competen[tț]e specifice)\s*[:.\n-]?\s*(.+?)(?=(?:^|\n)\s*(?:8\.\s*Contents?|Course Content|Programa detallado|Evaluación|Actividades|Evaluare|Assessment|Teaching|Bibliography|Bibliograf|\Z))",
                full_text,
                re.DOTALL | re.IGNORECASE
            )
            if comp_m:
                competencies = self._clean_noise_and_bibliography(comp_m.group(1))

        # Lab / Practical Topics
        lab_topics = None
        for k, v in table_cells.items():
            if any(lkw in k for lkw in ["laboratory", "laborator", "prácticas", "practicas", "practical load", "teaching methodology"]):
                cand = self._clean_noise_and_bibliography(v)
                if len(cand) >= 30:
                    lab_topics = cand
                    break
        if not lab_topics:
            lab_m = re.search(
                r"(?:^|\n)\s*(?:8\.2\s*Seminary\s*/\s*Laboratory|Laboratorios?|Pr[aá]cticas|Seminary\s*/\s*Laboratory)\s*[:.\n-]?\s*(.+?)(?=(?:^|\n)\s*(?:9\.\s*Corroborat|10\.\s*Assessment|Assessment|Evaluación|Evaluare|Bibliography|Bibliograf|\Z))",
                full_text,
                re.DOTALL | re.IGNORECASE
            )
            if lab_m:
                lab_topics = self._clean_noise_and_bibliography(lab_m.group(1))

        # Description
        description = objectives.split("\n")[0] if objectives else f"Course on {title}"

        return CanonicalCourse(
            university_name=detected_uni,
            study_program=study_program,
            code=code,
            title=title,
            title_en=title_en,
            ects=ects,
            semester=semester,
            year_of_study=year,
            language=language,
            course_type=course_type,
            optional_package="Elective Track" if course_type == "optional" else None,
            description=description,
            objectives=objectives,
            topics_lecture=lecture_topics,
            topics_seminar_lab=lab_topics,
            competencies=competencies,
            raw_text=full_text
        )

    def _is_extraction_valid(self, course: Optional[CanonicalCourse]) -> bool:
        """Evaluates extraction quality objectively before accepting Stage 1 output."""
        if not course or not course.title:
            return False
        clean_title = course.title.strip().lower()
        if len(clean_title) < 3 or clean_title.endswith(".pdf"):
            return False
        if not course.ects or course.ects <= 0.0:
            return False
        has_topics = len(course.topics_lecture or "") >= 80
        has_objectives = len(course.objectives or "") >= 80
        has_competencies = len(course.competencies or "") >= 80
        return has_topics or has_objectives or has_competencies


class LLMFallbackExtractor:
    """Stage 2: Universal LLM-based syllabus extractor fallback.
    
    Triggered exclusively when Stage 1 quality check fails. Uses structured output
    matching CanonicalCourse schema if an API key is configured (OpenAI or Gemini).
    Gracefully degrades to raw fallback in offline environments without raising exceptions.
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None
    ):
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")

    def _call_openai(self, text: str) -> Optional[Dict[str, Any]]:
        """Invokes OpenAI Chat Completion API with JSON structured output."""
        if not self.openai_api_key:
            return None
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.openai_api_key}"
        }
        prompt = (
            "Extract academic syllabus details from this document into valid JSON with fields: "
            "university_name, study_program, code, title, title_en, ects (float), semester (int 1-12), "
            "year_of_study (int 1-6), language ('en', 'es', 'ro', etc.), course_type ('mandatory' or 'optional'), "
            "objectives (string), topics_lecture (string), topics_seminar_lab (string), competencies (string)."
        )
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text[:8000]}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
        except Exception as e:
            logger.warning(f"OpenAI fallback call failed: {e}")
            return None

    def _call_gemini(self, text: str) -> Optional[Dict[str, Any]]:
        """Invokes Gemini REST API with JSON response mime type."""
        if not self.gemini_api_key:
            return None
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.gemini_api_key}"
        headers = {"Content-Type": "application/json"}
        prompt = (
            "Extract academic syllabus details from this document into valid JSON with fields: "
            "university_name, study_program, code, title, title_en, ects (float), semester (int 1-12), "
            "year_of_study (int 1-6), language ('en', 'es', 'ro', etc.), course_type ('mandatory' or 'optional'), "
            "objectives (string), topics_lecture (string), topics_seminar_lab (string), competencies (string)."
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"text": text[:8000]}
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1
            }
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(content)
        except Exception as e:
            logger.warning(f"Gemini fallback call failed: {e}")
            return None

    def extract(self, file_path: str, university_name: Optional[str] = None) -> Tuple[CanonicalCourse, str]:
        """Performs LLM structured extraction if configured, or degrades to offline raw extraction."""
        path = Path(file_path)
        raw_text = ""
        try:
            with pdfplumber.open(path) as pdf:
                raw_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception as e:
            logger.warning(f"Failed extracting raw text for fallback: {e}")
            raw_text = f"Syllabus file: {path.name}"

        # 1. Attempt LLM extraction if API key is present
        llm_data = None
        if self.openai_api_key:
            llm_data = self._call_openai(raw_text)
        elif self.gemini_api_key:
            llm_data = self._call_gemini(raw_text)

        if llm_data and isinstance(llm_data, dict) and llm_data.get("title"):
            try:
                course = CanonicalCourse(
                    university_name=llm_data.get("university_name") or university_name or path.parent.name.upper(),
                    study_program=llm_data.get("study_program") or "Computer Science",
                    code=llm_data.get("code") or path.stem,
                    title=llm_data.get("title"),
                    title_en=llm_data.get("title_en"),
                    ects=float(llm_data.get("ects") or 6.0),
                    semester=llm_data.get("semester"),
                    year_of_study=llm_data.get("year_of_study"),
                    language=llm_data.get("language") or "en",
                    course_type=llm_data.get("course_type") or "mandatory",
                    objectives=llm_data.get("objectives"),
                    topics_lecture=llm_data.get("topics_lecture"),
                    topics_seminar_lab=llm_data.get("topics_seminar_lab"),
                    competencies=llm_data.get("competencies"),
                    raw_text=raw_text
                )
                return course, "llm_fallback"
            except Exception as e:
                logger.warning(f"Failed parsing LLM dictionary into CanonicalCourse: {e}")

        # 2. Offline graceful degradation (raw fallback)
        clean_stem = path.stem.replace("_", " ").replace("-", " ")
        uni = university_name or path.parent.name.upper() or "Partner University"
        first_line = raw_text.splitlines()[0] if raw_text.splitlines() else clean_stem
        title = first_line[:80].strip() if len(first_line.strip()) > 3 else clean_stem

        course = CanonicalCourse(
            university_name=uni,
            study_program="Computer Science",
            code=path.stem,
            title=title,
            title_en=title,
            ects=6.0,
            semester=None,
            year_of_study=None,
            language="en",
            course_type="mandatory",
            description=f"Course syllabus extracted from {path.name}",
            objectives=f"Course overview for {title}",
            topics_lecture=" ".join(raw_text.split()[:300]),
            raw_text=raw_text
        )
        return course, "raw_fallback"


class HybridSyllabusParser:
    """Orchestrator for the two-stage syllabus parsing architecture.
    
    Coordinates UniversalBolognaParser (Stage 1), quality gate verification,
    and LLMFallbackExtractor (Stage 2).
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None
    ):
        self.stage1_parser = UniversalBolognaParser()
        self.stage2_extractor = LLMFallbackExtractor(
            openai_api_key=openai_api_key,
            gemini_api_key=gemini_api_key
        )

    def parse(self, file_path: str, university_name: Optional[str] = None) -> Tuple[CanonicalCourse, str]:
        """Runs two-stage extraction pipeline returning the CanonicalCourse and the winning strategy.
        
        Returns:
            Tuple[CanonicalCourse, str]: Extracted course and strategy identifier:
            'universal_bologna', 'llm_fallback', or 'raw_fallback'.
        """
        try:
            course = self.stage1_parser.parse(file_path, university_name=university_name)
            if self.stage1_parser._is_extraction_valid(course):
                return course, "universal_bologna"
            logger.info(f"Stage 1 quality check failed for {file_path}. Triggering LLMFallbackExtractor...")
        except Exception as e:
            logger.warning(f"Stage 1 parser encountered error on {file_path}: {e}. Triggering fallback...")

        # Stage 1 quality gate failed or raised error -> Trigger Stage 2
        return self.stage2_extractor.extract(file_path, university_name=university_name)

    def parse_single_pdf(self, file_path: str, university_name: Optional[str] = None, uni_key: Optional[str] = None) -> CanonicalCourse:
        """Backward-compatible helper returning solely the CanonicalCourse instance."""
        target_uni = university_name or (uni_key.upper() if uni_key else None)
        course, _ = self.parse(file_path, university_name=target_uni)
        return course

    def parse_directory(self, directory_path: str, university_name: Optional[str] = None) -> CurriculumPackage:
        """Parses all PDF syllabi in a directory into a CurriculumPackage."""
        path = Path(directory_path)
        pdf_files = list(path.glob("*.pdf"))
        courses: List[CanonicalCourse] = []
        uni_name = university_name or path.name.upper()

        for pdf in pdf_files:
            course, strat = self.parse(str(pdf), university_name=uni_name)
            courses.append(course)

        return CurriculumPackage(
            university_name=uni_name,
            study_program="Computer Science",
            academic_year="2023-2024",
            degree_cycle="bachelor",
            courses=courses
        )


# Singleton instances for dependency injection and backward compatibility
parser_service = HybridSyllabusParser()
SyllabusParserService = HybridSyllabusParser
