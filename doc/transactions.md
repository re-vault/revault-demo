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

## unvault_tx

The transaction which spends the funding transaction, only spendable after 6
blocks.

- version: 2
- locktime: 0

#### IN

- count: 1
- inputs[0]:
    - txid: `<vault_tx txid>`
    - sequence: `0xffffffff`
    - scriptSig: `<empty>`
    - witness: `0 <sig pubkey1> <sig pubkey2> <sig pubkey3> <sig pubkey4>`

#### OUT

- count: 1
- outputs[0]:
    - value: `<vault_tx output value - tx_fee>`
    - scriptPubkey: `0x00 0x20 SHA256(<script>)`, with
        ```
        <script> =
        <trader1_pubkey> OP_CHECKSIG OP_SWAP <trader2_pubkey> OP_CHECKSIG OP_ADD OP_SWAP <stakeholder_pubkey> OP_CHECKSIG OP_ADD OP_DUP 3 OP_EQUAL
        OP_IF
            OP_SWAP <D> OP_CHECKSIG
        OP_ELSE
            2 OP_EQUALVERIFY <SERVER> OP_CHECKSIGVERIFY 6 OP_CHECKSEQUENCEVERIFY
        OP_ENDIF
        ```

## spend_tx

The transaction which spends the unvaulting transaction, only spendable after 6
blocks.

- version: 2
- locktime: 0

#### IN

- count: 1
- inputs[0]:
    - txid: `<unvault_tx txid>`
    - sequence: `0x00000006`
    - scriptSig: `<empty>`
    - witness: `0 <sig pubkey1> <sig pubkey2> <sig pubkey3> <sig pubkey4> <unvault_tx's locking script>`

#### OUT

- count: 1
- outputs[0]:
    - value: `<vault_tx output value - tx_fee>`
    - scriptPubkey: not specified


## emergency_txs

### vault_emergency_tx

This transaction takes coins from a `vault_tx` and locks them to a 4-of-4 (with the 4 keys
being differents from the vault keys).

- version: 2
- locktime: 0

#### IN

- count: 1
- inputs[0]:
    - txid: `<vault_tx txid>`
    - sequence: `0xffffffff`
    - scriptSig: `<empty>`
    - witness: `0 <sig pubkey1> <sig pubkey2> <sig pubkey3> <sig pubkey4> <vault_tx's locking script>`

#### OUT

- count: 1
- outputs[0]:
    - value: `<vault_tx output value - fees>`
    - scriptPubkey: `0x00 0x20 SHA256(<script>)`, with
        ```
        <script> = 4 <emer_pubkey1> <emer_pubkey2> <emer_pubkey3> <emer_pubkey4> 4 OP_CHECKMULTISIG
        ```

### unvault_emergency_tx

This transaction takes coins from an `unvault_tx` and locks them to a 4-of-4 (with the 4 keys
being differents from the vault keys).

- version: 2
- locktime: 0

#### IN

- count: 1
- inputs[0]:
    - txid: `<unvault_tx txid>`
    - sequence: `0xffffffff` # FIXME: RBF ?
    - scriptSig: `<empty>`
    - witness: `0 <sig pubkey1> <sig pubkey2> <sig pubkey3> <sig pubkey4> <unvault_tx's locking script>`

#### OUT

- count: 1
- outputs[0]:
    - value: `<unvault_tx output value - fees>`
    - scriptPubkey: `0x00 0x20 SHA256(<script>)`, with
        ```
        <script> = 4 <emer_pubkey1> <emer_pubkey2> <emer_pubkey3> <emer_pubkey4> 4 OP_CHECKMULTISIG
        ```
