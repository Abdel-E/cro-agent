"""Ensure tests never pick up repo `.env` Gemini settings.

`app.main` loads `.env` before `BanditState` is created. These values must be
set *before* `test_api` (or any module) imports `app.main`, so pytest loads
this conftest first.
"""

from __future__ import annotations

import os

# Block `.env` from overriding (python-dotenv skips vars already in os.environ).
os.environ["COPY_GENERATOR_BACKEND"] = "mock"
os.environ["GOOGLE_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["AGENT_REASONER_BACKEND"] = "mock"
