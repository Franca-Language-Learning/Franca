"""Settings, database access and logging, used by every module. Imports no other franca package."""

from franca.platform.settings import Settings, load_settings

__all__ = ["Settings", "load_settings"]
