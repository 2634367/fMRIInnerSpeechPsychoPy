"""Question bank loading and run construction.

A question is a JSON object:

    {"uuid": ..., "category": ..., "view": "text"|"shapes"|"image",
     "text": ..., "answer": "yes"|"no", "family": ...,
     "params": { ...view-specific... }}

`family` groups paraphrases and close variants so they can be kept in the same
machine-learning fold later.
"""
import json
import math

FLIP = {"yes": "no", "no": "yes"}


def load(path):
    questions = json.loads(open(path, encoding="utf-8").read())
    seen = set()
    for q in questions:
        for key in ("uuid", "category", "view", "text", "answer"):
            if key not in q:
                raise ValueError(f"question missing `{key}`: {q}")
        if q["answer"] not in FLIP:
            raise ValueError(f"answer must be yes/no: {q}")
        if q["uuid"] in seen:
            raise ValueError(f"duplicate uuid: {q['uuid']}")
        seen.add(q["uuid"])
        q.setdefault("family", q["uuid"])
        q.setdefault("params", {})
    return questions


# ---------------------------------------------------------------- jitter ---
def bounds(phase, tr):
    """The shortest and longest duration the task can draw for a phase."""
    dur = phase["dur"]
    if not isinstance(dur, (list, tuple)):
        return float(dur), float(dur)
    lo, hi = float(dur[0]), float(dur[1])
    if phase.get("jitter") == "geometric":      # whole TRs, so `hi` may be out of reach
        hi = round(lo + math.floor((hi - lo) / tr + 1e-9) * tr, 4)
    return lo, hi


def sample_duration(phase, rng, tr=None, round_to_tr=False):
    dur = phase["dur"]
    if not isinstance(dur, (list, tuple)):
        return float(dur)
    lo, hi = float(dur[0]), float(dur[1])
    kind = phase.get("jitter", "uniform")
    if kind == "geometric":
        # Truncated geometric (textbook eq. 5.3): lo plus n whole TRs. Memoryless
        # up to the cap, so the participant cannot anticipate the next event,
        # and already on the TR grid, so no rounding afterwards.
        n_max = int(math.floor((hi - lo) / tr + 1e-9))
        return round(lo + _truncated_geometric(phase.get("p", 0.5), n_max, rng) * tr, 4)
    if kind == "exponential":
        # Truncated exponential: short gaps are more common, which is the
        # standard efficient choice for event-related fMRI designs.
        lam = 1.0 / (0.35 * (hi - lo))
        u = rng.random()
        value = lo - math.log(1.0 - u * (1.0 - math.exp(-lam * (hi - lo)))) / lam
    else:
        value = rng.uniform(lo, hi)
    if round_to_tr and tr:
        value = max(lo, round(value / tr) * tr)
    return round(min(value, hi), 4)


def _truncated_geometric(p, n_max, rng):
    """Draw n in 0..n_max with P(n) proportional to p (1 - p)^n.

    One uniform draw, then walk the cumulative probabilities - with p = 0.5 and
    n_max = 4 the cut points are 16/31, 24/31, 28/31, 30/31.
    """
    weights = [(1.0 - p) ** n for n in range(n_max + 1)]
    u = rng.random() * sum(weights)
    for n, w in enumerate(weights):
        u -= w
        if u < 0:
            return n
    return n_max


# ------------------------------------------------------------ run builder ---
def _pick(pool, answer, rng, used):
    """Take one question with the requested answer, preferring unused ones."""
    matching = [q for q in pool if q["answer"] == answer]
    if not matching:
        raise ValueError(f"question bank has no `{answer}` items left to draw")
    fresh = [q for q in matching if q["uuid"] not in used]
    chosen = rng.choice(fresh or matching)
    used.add(chosen["uuid"])
    return chosen, bool(fresh)


def build_run(questions, cfg, rng, already_seen=()):
    """Return the ordered trial list for one run.

    Labels are balanced within every condition, and trials are shuffled inside
    blocks so both labels are spread evenly across the run.
    """
    conditions = cfg["conditions"]
    n_blocks = cfg["run"]["n_blocks"]
    per_block = cfg["run"]["trials_per_block"]
    tr = cfg["scanner"]["tr"]
    round_tr = cfg["trial"].get("round_jitter_to_tr", False)

    used = set(already_seen)
    reused = 0
    trials = []

    for name, spec in conditions.items():
        count = spec["per_run"]
        # split as evenly as possible; give the odd trial to a random label
        n_yes = count // 2
        answers = ["yes"] * n_yes + ["no"] * (count - n_yes)
        if count % 2:
            answers[-1] = rng.choice(["yes", "no"])
        for answer in answers:
            question, was_fresh = _pick(questions, answer, rng, used)
            reused += not was_fresh
            trials.append(_make_trial(question, name, spec, cfg, rng, tr, round_tr))

    # Shuffle globally, then cut into blocks and shuffle within each block.
    rng.shuffle(trials)
    ordered = []
    for b in range(n_blocks):
        block = trials[b * per_block:(b + 1) * per_block]
        rng.shuffle(block)
        for i, trial in enumerate(block):
            trial["block"] = b
            trial["index_in_block"] = i
            trial["trial"] = len(ordered)
            ordered.append(trial)
    return ordered, reused


def _make_trial(question, condition, spec, cfg, rng, tr, round_tr):
    answer = question["answer"]
    mode = spec.get("response", "answer")
    response = {"answer": answer, "opposite": FLIP[answer],
                "none": None, "ready": "ready"}[mode]

    cue = response.upper() if spec.get("cue_from_response") and response else spec["cue"]

    durations = {
        p["name"]: sample_duration(p, rng, tr, round_tr) for p in cfg["trial"]["phases"]
    }
    return {
        "question_uuid": question["uuid"],
        "category": question["category"],
        "family": question["family"],
        "view": question["view"],
        "text": question["text"],
        "params": question["params"],
        "answer": answer,             # truth of the proposition
        "condition": condition,
        "response_token": response,   # what the participant actually repeats
        "cue": cue,
        "show_question": spec.get("show_question", True),
        "durations": durations,
    }
