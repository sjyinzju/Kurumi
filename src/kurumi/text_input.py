"""Model-facing text sections and research conditions shared by build and training."""

BUDGET = 1024
TRAIN_CONDITIONS = {"G0": "none", "GN": "news", "GA": "announcement", "GNA": "both"}
ALL_CONDITIONS = frozenset(TRAIN_CONDITIONS.values())


def text_condition(group, phase, *, no_text_diagnostic=False):
    if group not in TRAIN_CONDITIONS:
        raise ValueError(f"Unknown research group {group!r}")
    if no_text_diagnostic:
        if phase not in ("validation", "calibration", "test", "inference") or group not in ("G0", "GNA"):
            raise ValueError("The no-text diagnostic applies to evaluation of G0 and GNA")
        return "none"
    if phase == "train":
        return TRAIN_CONDITIONS[group]
    if phase in ("validation", "calibration", "test", "inference"):
        return "both"
    raise ValueError(f"Unknown research phase {phase!r}")


def section_text(modality, blocks):
    heading = "[News]" if modality == "news" else "[Company announcements]"
    return heading + "\n" + "\n\n".join(blocks) if blocks else heading + "\n—"
