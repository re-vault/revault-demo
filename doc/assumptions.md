- We assume there is at least one honest watcher with access to the Bitcoin network.
- We assume the cosigner(s) to enforce the "sign-only-once" rule.
- We assume noone refuse to sign.
- We assume that not all the private keys of a vault utxo can be compromised at once,
    until this vault is spent.
- We assume the N static emergency private keys are not compromised at once.
- We assume a significant hashrate to lower the probability of X blocks (with X the CSV
    timelock of the unvault transaction) being mined in a very small amount of time down
    to 0.
