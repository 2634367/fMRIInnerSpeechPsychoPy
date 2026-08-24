"""Text plus an image, for image-evoked questions.

params: {"image": "sparrow.png", "size": [0.35, 0.35]}
Paths are relative to `paths.images_dir` in the config.
"""
from psychopy import visual

from .base import View


class ImageView(View):
    def build(self):
        self.title = self._text(pos=self.cfg["text"]["title_pos"])
        self.images_dir = self.cfg.path("images_dir")
        self.stim = visual.ImageStim(self.win, image=None, pos=(0, -0.05))

    def prepare(self, trial):
        self.title.text = trial["text"]
        params = trial["params"]
        path = self.images_dir / params["image"]
        if not path.exists():
            raise FileNotFoundError(f"image not found: {path}")
        self.stim.image = str(path)
        if params.get("size"):
            self.stim.size = params["size"]

    def draw(self):
        self.title.draw()
        self.stim.draw()
