# Vaultaic transactions

All transactions use native Segwit.

- [vault_tx](#vault_tx)
- unvault_tx
- spend_tx
- cancel_tx
- [emergency_txs](#emergency_txs)
    - [vault_emergency_tx](#vault_emergency_tx)
    - unvault_emergency_tx

## vault_tx

The funding transaction.

#### IN

We don't care about the inputs.

#### OUT

At least one output paying to the following script:
```
0x00 0x20 SHA256(<script>)
```
With
```
<script> = 4 <pubkey1> <pubkey2> <pubkey3> <pubkey4> 4 OP_CHECKMULTISIG
```

## emergency_txs

### vault_emergency_tx

This transaction takes coins from a `vault_tx` and locks them to a 4-of-4 with 4 different keys.

- version: 2
- locktime: 0

#### IN

- count: 1
- inputs[0]:
    - txid: `<vault_tx txid>`
    - sequence: `0xffffffff`
    - scriptSig: `<empty>`
    - witness: `0 <pubkey1> <pubkey2> <pubkey3> <pubkey4>`

#### OUT

- count: 1
- outputs[0]:
    - value: `<vault_tx output value - fees>`
    - scriptPubkey: `0x00 0x20 SHA256(<script>)`, with
        ```
        <script> = 4 <emer_pubkey1> <emer_pubkey2> <emer_pubkey3> <emer_pubkey4> 4 OP_CHECKMULTISIG
        ```
