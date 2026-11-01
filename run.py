import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from app.main import run
except ModuleNotFoundError as exc:
    preferred_python = PROJECT_ROOT / ".venv312" / "Scripts" / "python.exe"
    if (
        preferred_python.is_file()
        and Path(sys.executable).resolve() != preferred_python.resolve()
    ):
        os.execv(
            str(preferred_python),
            [str(preferred_python), str(Path(__file__).resolve()), *sys.argv[1:]],
        )
    raise SystemExit(
        f"Cannot start the app: Python is missing '{exc.name}'. "
        "Select the project's .venv312 interpreter in VS Code or install "
        "dependencies with: python -m pip install -r requirements.txt"
    ) from exc

if __name__ == "__main__":
    run()
