import os
import sys

# Ensure imports like `from app.main import app` work when running pytest from /src
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))