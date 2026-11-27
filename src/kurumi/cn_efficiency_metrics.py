"""Paired probability evaluation on dated, inverse-inclusion-weighted originals."""

import numpy as np
from scipy.special import logsumexp


def log_probabilities(models, x):
    out = []
    for model, columns in models:
        logits = model.decision_function(x[:, columns])
        out.append(logits - logsumexp(logits, axis=-1, keepdims=True))
    return np.stack(out, axis=1)


def prior_log_probabilities(fit, size):
    priors = []
    for targets in fit["targets"].T:
        observed = targets >= 0
        counts = np.bincount(targets[observed], weights=fit["weights"][observed], minlength=7)
        if (counts <= 0).any():
            raise ValueError("The fit view must cover all seven outcome classes")
        priors.append(np.log(counts / counts.sum()))
    return np.broadcast_to(priors, (size, len(priors), 7))


def probability_scores(log_prob, targets):
    """Return CE, seven-class Brier, normalized RPS, accuracy, and L, retaining the mask."""
    if log_prob.shape != (*targets.shape, 7) or not np.isfinite(log_prob).all():
        raise ValueError("Expected seven finite log probabilities for each original and horizon")
    valid = targets >= 0
    y = targets.clip(min=0)
    prob = np.exp(log_prob)
    if not np.allclose(prob.sum(axis=2), 1, atol=1e-7):
        raise ValueError("Class probabilities must sum to one")
    ce = -np.take_along_axis(log_prob, y[:, :, None], axis=2)[:, :, 0]
    residual = prob - np.eye(7)[y]
    brier = (residual ** 2).sum(axis=2)
    rps = (residual.cumsum(axis=2)[:, :, :6] ** 2).mean(axis=2)
    accuracy = prob.argmax(axis=2) == y
    scores = np.stack((ce, brier, rps, accuracy, ce + 0.5 * brier + 0.5 * rps), axis=2)
    return np.where(valid[:, :, None], scores, np.nan)


def original_scores(values, valid):
    counts = valid.sum(axis=1)
    if not counts.all():
        raise ValueError("Every evaluated original must have an effective target")
    return np.where(valid, values, 0).sum(axis=1) / counts


def paired_originals(candidate, baseline, valid, months, weights, *, draws=2000, seed=17,
                     window_upper=0.01, horizon_point=0.02):
    """Average horizons within each original before weighting and resampling whole months."""
    delta = candidate - baseline
    items = original_scores(delta, valid)
    mass = (weights[:, None] * valid).sum(axis=0)
    horizon = (weights[:, None] * np.where(valid, delta, 0)).sum(axis=0)
    horizon = np.divide(horizon, mass, out=np.full_like(horizon, np.nan), where=mass > 0)
    blocks, index = np.unique(months, return_inverse=True)
    total_by_block = np.bincount(index, weights=weights * items)
    weight_by_block = np.bincount(index, weights=weights)
    bounds = None
    if len(blocks) >= 2:
        sampled = np.random.default_rng(seed).integers(0, len(blocks), size=(draws, len(blocks)))
        resampled = total_by_block[sampled].sum(axis=1) / weight_by_block[sampled].sum(axis=1)
        bounds = np.quantile(resampled, [0.025, 0.975]).tolist()
    return {
        "original_weighted_objective_delta": float(np.average(items, weights=weights)),
        "original_weighted_month_bootstrap_95": bounds,
        "objective_delta_by_horizon": {str(h): float(d) if np.isfinite(d) else None
                                       for h, d in zip((1, 5, 20), horizon, strict=True)},
        "originals": len(items),
        "months": len(blocks),
        "passes_cpu_noninferiority": bool(bounds and bounds[1] <= window_upper
                                          and (horizon[mass > 0] <= horizon_point).all()),
    }


def calibration(prob, targets, weights):
    """Weighted reliability bins for top-label confidence and each of the seven classes."""
    confidence = prob.max(axis=1)
    predictions = prob.argmax(axis=1)

    def ece(p, correct):
        bins = np.minimum((p * 10).astype(int), 9)
        mass = np.bincount(bins, weights=weights, minlength=10)
        probability = np.bincount(bins, weights=weights * p, minlength=10)
        observed = np.bincount(bins, weights=weights * correct, minlength=10)
        return float(np.abs(probability - observed).sum() / mass.sum()), [
            [float(m), float(c / m), float(o / m)] if m else [0, None, None]
            for m, c, o in zip(mass, probability, observed, strict=True)
        ]

    top, bins = ece(confidence, predictions == targets)
    classes = [ece(prob[:, k], targets == k)[0] for k in range(7)]
    return dict(top_ece=top, class_ece=classes, macro_class_ece=float(np.mean(classes)), top_reliability=bins)
