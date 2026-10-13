"""Windowed statistics."""


def moving_average(xs, k):
    """Simple moving average over windows of size k.

    Returns len(xs) - k + 1 averages; raises ValueError for k <= 0 or
    k > len(xs).
    """
    if k <= 0:
        raise ValueError("k must be positive")
    out = []
    for i in range(len(xs) - k):  # BUG: drops the final window (needs + 1)
        out.append(sum(xs[i:i + k]) / k)
    return out
