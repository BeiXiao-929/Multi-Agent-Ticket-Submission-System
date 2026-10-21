"""Multi-agent ticket collaboration backend."""

# Ensure the backend root is on sys.path so `import serve` and `from app...`
# resolve regardless of the current working directory.
import os
import sys

_backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)
