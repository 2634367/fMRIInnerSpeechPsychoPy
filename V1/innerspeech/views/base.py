"""Base class for question views.

A view owns its PsychoPy stimuli. Stimuli are created once when the view is
built and only reconfigured per trial, which keeps the frame loop cheap.
"""
from psychopy import visual


class View:
    """Subclasses implement `build`, `prepare` and `draw`."""

    def __init__(self, win, cfg):
        self.win = win
        self.cfg = cfg
        self.build()

    def build(self):
        """Create stimuli. Called once."""

    def prepare(self, trial):
        """Load one trial's content into the stimuli. Called between trials."""
        raise NotImplementedError

    def draw(self):
        """Draw the current content. Called every frame."""
        raise NotImplementedError

    # helper shared by every view
    def _text(self, pos=(0, 0)):
        t = self.cfg["text"]
        return visual.TextStim(
            self.win, text="", font=t["font"], height=t["height"],
            color=t["color"], wrapWidth=t["wrap_width"], pos=pos, alignText=t["align"],
        )
