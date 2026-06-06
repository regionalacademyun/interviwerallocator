from pathlib import Path
import unicodedata

APP_TITLE = "RAUN Interview Allocation Studio"
APP_SUBTITLE = "Interview candidate dashboard, interviewer availability, and interview allocation"
APP_PASSWORD = "password"
DEFAULT_USERNAME = ""
NEW_USER_LABEL = "New user / guest reviewer"
GOOGLE_SERVICE_ACCOUNT_FILE = ""


def normalize_name_for_sort(name: str) -> str:
    return unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("utf-8").lower().strip()


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

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUTS_DIR = BASE_DIR / "outputs"
TEMP_DIR = BASE_DIR / "temp"
ASSETS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

LOGO_CANDIDATES = [
    ASSETS_DIR / "RAUN logo.png",
    ASSETS_DIR / "RAUN_logo.png",
    ASSETS_DIR / "raun_logo.png",
]
