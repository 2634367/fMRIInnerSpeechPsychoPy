"""Text-only view: the question, centred. Used by most question families."""
from .base import View


class TextView(View):
    def build(self):
        self.stim = self._text(pos=(0, 0))

    def prepare(self, trial):
        self.stim.text = trial["text"]

    def draw(self):
        self.stim.draw()
