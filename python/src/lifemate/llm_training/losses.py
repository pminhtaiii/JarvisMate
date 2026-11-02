"""Completion means and globally normalized row weighting, exactly once per window."""
import math


def mean_weight(rows, weights):
    if not rows:
        raise ValueError("Accepted clean Fit bases are empty")
    return sum(weights[r["target_type"]] for r in rows) / len(rows)


def weighted_objective(row_loss, weight, mu_w, actual_window):
    if not all(math.isfinite(x) and x > 0 for x in (weight, mu_w)) or type(actual_window) is not int or actual_window <= 0:
        raise ValueError("Invalid row weight/window")
    return row_loss * (weight / mu_w) / actual_window


def completion_loss(model, tokens, torch):
    """Compute logits only at supervised predecessor positions, avoiding a 16K*vocab tensor."""
    ids, labels = tokens["input_ids"], tokens["labels"]
    if len(ids) != len(labels) or not ids or any(type(i) is not int for i in ids):
        raise ValueError("Invalid token cache")
    positions = [i for i, label in enumerate(labels) if label != -100]
    if (not positions or positions[0] == 0 or positions != list(range(positions[0], len(ids)))
            or any(labels[i] != ids[i] for i in positions)):
        raise ValueError("Exactly one contiguous completion including EOS is required")
    eos = model.config.eos_token_id
    completion = [labels[i] for i in positions]
    if type(eos) is not int or completion[-1] != eos or completion.count(eos) != 1:
        raise ValueError("Completion loss requires exactly one pinned assistant EOS")
    device = next(model.parameters()).device
    input_ids = torch.tensor([ids], device=device)
    predecessors = torch.tensor([i - 1 for i in positions], device=device)
    targets = torch.tensor([labels[i] for i in positions], device=device)
    logits = model(input_ids=input_ids, attention_mask=torch.ones_like(input_ids),
                   logits_to_keep=predecessors, use_cache=False).logits[0].float()
    if logits.shape[0] != len(positions):
        raise ValueError("Model does not support exact supervised-position logits")
    return torch.nn.functional.cross_entropy(logits, targets, reduction="mean")


def optimizer_update(model, optimizer, scheduler, scaler, window, weights, mu_w, torch, *, on_row=None):
    if not window:
        raise ValueError("Empty accumulation window")
    optimizer.zero_grad(set_to_none=True)
    losses = []
    for tokens, kind in window:
        loss = completion_loss(model, tokens, torch)
        if not torch.isfinite(loss):
            raise ValueError("Nonfinite completion loss")
        objective = weighted_objective(loss, weights[kind], mu_w, len(window))
        scaler.scale(objective).backward()
        losses.append({"unweighted": float(loss.detach()), "weighted": float(objective.detach()),
                       "tokens": tokens["completion_tokens"], "target_type": kind})
        if on_row is not None:
            on_row(len(losses), len(window))
    scaler.unscale_(optimizer)
    trainable = [p for p in model.parameters() if p.requires_grad]
    if not any(p.grad is not None for p in trainable) or any(p.grad is not None and not torch.isfinite(p.grad).all() for p in trainable):
        raise ValueError("Missing/nonfinite adapter gradient")
    norm = torch.nn.utils.clip_grad_norm_(trainable, 1.0, error_if_nonfinite=True)
    before = [p.detach().clone() for p in trainable]
    scaler.step(optimizer)
    scaler.update()
    if not any(not torch.equal(a, b.detach()) for a, b in zip(before, trainable)):
        raise ValueError("No adapter update (possibly skipped scaler step)")
    scheduler.step()
    return {"rows": len(window), "gradient_norm": float(norm), "losses": losses}
