"""Batch working files are local; single-image legacy workflows retain their paths."""
import os
from pathlib import Path
from .profiles import BASE
WORK_ROOT=Path(os.environ.get('CELL_OVATER_WORK_ROOT',str(BASE/'outputs'))).expanduser().resolve()
