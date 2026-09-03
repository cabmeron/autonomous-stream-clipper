import sys
from pathlib import Path

# Ensure project root is on sys.path for test discovery
root_dir = str(Path(__file__).parent.resolve())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
