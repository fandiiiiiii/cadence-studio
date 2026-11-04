import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("CADENCE_DATA_DIR", tempfile.mkdtemp(prefix="cadence-test-"))
