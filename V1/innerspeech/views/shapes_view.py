"""Text plus geometric shapes, for perceptual and relational questions.

params: {"shapes": [{"kind": "triangle", "pos": [0, 0.06], "size": 0.08,
                     "color": "white", "ori": 0}, ...]}
"""
from psychopy import visual

from .base import View

EDGES = {"triangle": 3, "square": 4, "diamond": 4, "pentagon": 5,
         "hexagon": 6, "circle": 64}
DEFAULT_ORI = {"square": 45.0}     # PsychoPy polygons point up; rotate to square it
MAX_SHAPES = 6


class ShapesView(View):
    def build(self):
        self.title = self._text(pos=self.cfg["text"]["title_pos"])
        self.pool = [
            visual.Polygon(self.win, edges=3, radius=0.08, pos=(0, 0),
                           fillColor="white", lineColor="white")
            for _ in range(MAX_SHAPES)
        ]
        self.active = []

    def prepare(self, trial):
        self.title.text = trial["text"]
        specs = trial["params"].get("shapes", [])[:MAX_SHAPES]
        self.active = []
        for spec, stim in zip(specs, self.pool):
            kind = spec["kind"]
            if kind not in EDGES:
                raise ValueError(f"unknown shape kind `{kind}`")
            stim.edges = EDGES[kind]
            stim.radius = spec.get("size", 0.08)
            stim.ori = spec.get("ori", DEFAULT_ORI.get(kind, 0.0))
            stim.pos = spec["pos"]
            colour = spec.get("color", "white")
            stim.fillColor = colour
            stim.lineColor = colour
            self.active.append(stim)

    def draw(self):
        self.title.draw()
        for stim in self.active:
            stim.draw()
