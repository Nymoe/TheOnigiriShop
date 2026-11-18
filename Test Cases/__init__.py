"""Make the source modules and test helpers available during discovery."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parent.parent / 'Source'))
