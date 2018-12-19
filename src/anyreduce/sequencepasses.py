def find_integer(f):
    """Finds a (hopefully large) integer such that f(n) is True and f(n + 1) is
    False.
    f(0) is assumed to be True and will not be checked.
    """
    # We first do a linear scan over the small numbers and only start to do
    # anything intelligent if f(4) is true. This is because it's very hard to
    # win big when the result is small. If the result is 0 and we try 2 first
    # then we've done twice as much work as we needed to!
    for i in range(1, 5):
        if not f(i):
            return i - 1

    # We now know that f(4) is true. We want to find some number for which
    # f(n) is *not* true.
    # lo is the largest number for which we know that f(lo) is true.
    lo = 4

    # Exponential probe upwards until we find some value hi such that f(hi)
    # is not true. Subsequently we maintain the invariant that hi is the
    # smallest number for which we know that f(hi) is not true.
    hi = 5
    while f(hi):
        lo = hi
        hi *= 2

    # Now binary search until lo + 1 = hi. At that point we have f(lo) and not
    # f(lo + 1), as desired..
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if f(mid):
            lo = mid
        else:
            hi = mid
    return lo


def linear_reduce(sequence, predicate):
    """Runs a single forward pass that attempts to reduce sequence subject
    to the condition that predicate returns True, guaranteeing that it has tried
    removing every single element in the input. Runs in O(log(n) + m) where
    n is the size of the input and m is the size of the answer."""

    prev = len(sequence) + 1
    i = 0
    while i < len(sequence):
        prev = sequence
        prefix = sequence[:i]
        n = find_integer(
            lambda k: i + k <= len(sequence) and predicate(prefix + sequence[i + k :])
        )
        assert n >= 0
        if n > 0:
            sequence = prefix + sequence[i + n :]
        else:
            for offset in [2, 3]:
                if i + offset <= len(sequence):
                    attempt = prefix + sequence[i + offset :]
                    if predicate(attempt):
                        sequence = attempt
                        break
        if i + 2 < len(sequence):
            attempt = list(sequence)
            del attempt[i + 2]
            del attempt[i]
            if predicate(attempt):
                sequence = attempt
                break
        if len(prev) == len(sequence):
            i += 1
        else:
            i = max(0, i - 1)
    return sequence
