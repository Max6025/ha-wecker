"""Macht custom_components aus dem Projektordner fuer die Tests sichtbar.

Ausfuehren:  pip install pytest-homeassistant-custom-component
             pytest tests/
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.modules.pop("custom_components", None)
