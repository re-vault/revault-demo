# Vaultaic vaults

We call a "vault" a transaction output paying to a 4of4 multisig composed of the four
pubkeys at the *current index* of the given derivation path for the BIP32 key chain of each
of the stakeholders.

The derivation index starts at 0 and is increased each time a new vault is created. Note
that stakeholders may fail out of sync from each other according to the index. Worse thing
could be an address reuse, which we prefer to avoid but it not problematic at all for our
use case.

We use `m/0` as the derivation path for this demo.
