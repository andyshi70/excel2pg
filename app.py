"""Streamlit 入口： streamlit run app.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.main import main  # noqa: E402

main()
