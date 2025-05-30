import sys
import os

# Tambahkan direktori proyek ke Python path
# Ini penting agar Flask dapat menemukan app.py
sys.path.insert(0, os.path.dirname(__file__))

from app import app as application # 'application' adalah nama yang dicari Vercel