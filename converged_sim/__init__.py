"""Reproducible, synthetic FIFO bottleneck simulation for the course project.

The model is deliberately narrower than a real wireless link: packet arrivals,
FIFO admission, and a piecewise-constant service-rate trace are its only network
mechanisms.  It does not model MAC scheduling, loss on the air, or transport.
"""

from .config import DEFAULT_CONFIG, normalize_config
from .model import run_one

__all__ = ["DEFAULT_CONFIG", "normalize_config", "run_one"]
