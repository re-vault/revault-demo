def empty_signature():
    """This returns a NULL byte array for failing CHECKSIGs.

    Empty bytes arrays are require by bitcoind's standardness rules to avoid
    transactions malleability.
    """
    return bytes(0)


__all__ = [
    "empty_signature",
]
