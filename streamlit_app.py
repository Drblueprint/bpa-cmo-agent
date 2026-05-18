"""Root-level Streamlit entry point — fixes import path for Streamlit Cloud."""
import sys
import os

# Add repo root to path so `dashboard.*` imports resolve correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Run the actual dashboard
from dashboard.app import *
