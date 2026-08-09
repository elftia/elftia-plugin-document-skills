from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from document_skills_core.public_cli import main

if __name__ == "__main__":
    raise SystemExit(main(format_id="xlsx", project_root=PROJECT_ROOT))
