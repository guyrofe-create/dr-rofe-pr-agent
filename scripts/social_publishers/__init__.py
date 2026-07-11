"""Platform publisher modules for the Dr. Rofe PR Agent.

Each module exposes:
    is_configured() -> bool        # True if required secrets/env vars are present
    publish(title, body, url) -> str   # Returns a result URL/string, raises on hard failure
"""
