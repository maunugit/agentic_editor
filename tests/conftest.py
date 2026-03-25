"""Shared test configuration.

Loads environment variables from .env so tests can access GEMINI_API_KEY.
"""

from dotenv import load_dotenv

load_dotenv()
