# Standard
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("hermes")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__app_name__ = "Hermes"
__app_id__ = "Hermes"

