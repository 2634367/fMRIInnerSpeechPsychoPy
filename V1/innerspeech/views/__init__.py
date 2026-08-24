"""View registry.

Question types that only need words share `text`. Types that need graphics get
their own view. To add one: write a View subclass, register it below, and set
`"view": "<name>"` on the questions that use it.
"""
from .base import View
from .image_view import ImageView
from .shapes_view import ShapesView
from .text_view import TextView

REGISTRY = {"text": TextView, "shapes": ShapesView, "image": ImageView}


def build_all(win, cfg):
    """Instantiate every view once, up front."""
    return {name: cls(win, cfg) for name, cls in REGISTRY.items()}


__all__ = ["View", "REGISTRY", "build_all", "TextView", "ShapesView", "ImageView"]
