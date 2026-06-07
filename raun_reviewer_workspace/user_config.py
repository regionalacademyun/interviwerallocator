from __future__ import annotations
import unicodedata
from pathlib import Path

APP_TITLE = "RAUN Reviewer Assessment Workspace"
APP_SUBTITLE = "Reviewer scoring, interview invitation decisions, and assessment progress tracking"
APP_PASSWORD = "password"
DEFAULT_USERNAME = ""
NEW_USER_LABEL = "New user / guest reviewer"
ADMIN_USERS = {"Samar Momin", "Billy Batware"}

BASE_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BASE_DIR / "assets"
DOCS_DIR = BASE_DIR / "docs"
DATA_DIR = BASE_DIR / "data"
APPLICANT_DOCS_DIR = DATA_DIR / "applicant_documents"
SAMPLE_APPLICANT_DOCS_DIR = BASE_DIR / "sample_data" / "applicant_documents"

LOGO_CANDIDATES = [
    ASSETS_DIR / "raun_logo.png",
    BASE_DIR / "raun_logo.png",
]

def normalize_name_for_sort(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.casefold().strip()

RAUN_TEAM_MEMBERS = sorted([
    "Berkay Öztürk",
    "Billy Batware",
    "Cecilia Vera Lagomarsino",
    "Florian Müller",
    "Vanessa Moser",
    "Isabel Sáenz Hernández",
    "Ivy Omondi",
    "Laura María García",
    "Mariia Kostetckaia (Masha)",
    "Martina Pardy",
    "Mary Peloche",
    "Nicola Jansen",
    "Roman Hoffmann",
    "Samar Momin",
    "Thi Hoang",
], key=normalize_name_for_sort)

ALL_LOGIN_OPTIONS = [NEW_USER_LABEL] + RAUN_TEAM_MEMBERS
