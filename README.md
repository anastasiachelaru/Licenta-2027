# ErasmusMatch 🎓✈️

**ErasmusMatch** este o platformă inteligentă dedicată automatizării echivalării curriculare și generării acordurilor de studii (*Learning Agreements*) pentru studenții participanți la mobilități academice internaționale Erasmus+.

---

## 🚀 Arhitectură & Tehnologii

* **Backend:** FastAPI (Python)
* **Ingestie & Procesare Documente:** `pdfplumber` + regex & structuri canonice pentru extragerea metadatelor din fișele de disciplină (PDF).
* **NLP & Semantic Matching:** `sentence-transformers` (`paraphrase-multilingual-MiniLM-L12-v2`) pentru reprezentări vectoriale multilingve și calcul de similaritate cosinus între silabusuri din limbi diferite (română, engleză, spaniolă etc.).
* **Bază de date & Căutare Vectorială:** PostgreSQL 16 cu extensia `pgvector` (Docker).
* **Algoritm de Optimizare:** Constraint Satisfaction Problem (CSP) / Knapsack adaptat cu constrângeri stricte (materii obligatorii, refaceri) și flexibile (pachete opționale) pentru atingerea țintei de credite ECTS (ex. 30/35 ECTS).
* **Frontend:** React + TailwindCSS.
* **Export Documente:** Generare automată de draft Learning Agreement în format PDF.

---

## 📁 Structura Proiectului

```text
Licenta_ErasmusMatch/
├── backend/
│   ├── app/
│   │   ├── api/             # Rute și endpoint-uri REST FastAPI
│   │   ├── core/            # Configurare și setări aplicație
│   │   ├── db/              # Conexiune bază de date și modele ORM
│   │   ├── models/          # Scheme Pydantic (CanonicalCourse etc.)
│   │   ├── services/        # Servicii de parsare, embedding, solver, PDF
│   │   └── main.py          # Punctul de intrare FastAPI
│   ├── requirements.txt     # Dependințe Python
│   └── Dockerfile
├── docker/
│   └── docker-compose.yml   # PostgreSQL + pgvector
├── data/
│   ├── raw_syllabi/         # Fișe de disciplină originale (PDF)
│   └── processed/           # Date normalizate JSON
├── scripts/
│   └── parser.py            # Scripturi utilitare de extragere / testare
├── frontend/                # Aplicație React + TailwindCSS
└── README.md
```

---

## 🛠️ Ghid de Instalare Rapidă

### 1. Baza de date (PostgreSQL + pgvector)
```bash
docker compose -f docker/docker-compose.yml up -d
```

### 2. Backend
```bash
# Creează și activează un mediu virtual (Python 3.11 / 3.12 recomandat)
uv venv --python 3.11
.venv\Scripts\activate

# Instalare dependențe
uv pip install -r backend/requirements.txt
```
