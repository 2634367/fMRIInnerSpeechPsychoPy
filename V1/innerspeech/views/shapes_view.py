"""Text plus geometric shapes, for perceptual and relational questions.

params: {"shapes": [{"kind": "triangle", "pos": [0, 0.06], "size": 0.08,
                     "color": "white", "ori": 0}, ...]}

The shape kinds, their defaults and how many are drawn come from `views.shapes`
in the config.
"""
from psychopy import visual

from .base import View


class ShapesView(View):
    def build(self):
        self.spec = self.cfg["views"]["shapes"]
        self.title = self._text(pos=self.cfg["text"]["title_pos"])
        self.pool = [
            visual.Polygon(self.win, edges=3, radius=self.spec["size"], pos=(0, 0),
                           fillColor=self.spec["color"], lineColor=self.spec["color"])
            for _ in range(self.spec["max_shapes"])
        ]
        self.active = []

    def prepare(self, trial):
        self.title.text = trial["text"]
        edges, ori = self.spec["edges"], self.spec["default_ori"]
        specs = trial["params"].get("shapes", [])[:self.spec["max_shapes"]]
        self.active = []
        for spec, stim in zip(specs, self.pool):
            kind = spec["kind"]
            if kind not in edges:
                raise ValueError(f"unknown shape kind `{kind}` "
                                 f"(views.shapes.edges has {', '.join(edges)})")
            stim.edges = edges[kind]
            stim.radius = spec.get("size", self.spec["size"])
            stim.ori = spec.get("ori", ori.get(kind, 0.0))
            stim.pos = spec["pos"]
            colour = spec.get("color", self.spec["color"])
            stim.fillColor = colour
            stim.lineColor = colour
            self.active.append(stim)

    def draw(self):
        self.title.draw()
        for stim in self.active:
            stim.draw()
