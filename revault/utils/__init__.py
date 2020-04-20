from base58 import b58decode_check
from bitcoin.core import (
    CTxIn, CTxOut, COutPoint, CTxWitness, CTxInWitness,
    CMutableTxIn, CMutableTxOut, CMutableTransaction, COIN, CScript,
    Hash160, b2lx, lx,
)
from bitcoin.core.script import (
    CScriptWitness, SIGHASH_ALL, SIGVERSION_WITNESS_V0, SignatureHash, OP_0,
)
from bitcoin.wallet import CBitcoinAddress, CKey
from decimal import Decimal


# FIXME: introduce weights into python-bitcoinlib


def tx_fees(bitcoind, tx, prevouts_amount=None):
    """Computes the transaction fees of a CTransaction.

    :param bitcoind: The bitcoind RPC connection, to get the prevouts' value.
    :param tx: The CTransaction to get the fees of.
    :param prevouts_amount: The sum of the value of all the consumed outputs.

    :return: (int) The fees of the tx.
    """
    # FIXME: We workaround lack of txindex in bitcoindapi but..
    value_in = sum(
        bitcoind.getrawtransaction(
            b2lx(txin.prevout.hash), True
            # bitcoind API in btc...
        )["vout"][txin.prevout.n]["value"] * Decimal(COIN) for txin in tx.vin
    ) if prevouts_amount is None else prevouts_amount
    value_out = sum(o.nValue for o in tx.vout)

    return value_in - value_out


def tx_feerate(bitcoind, tx, prevouts_amount=None):
    """Get the feerate of a CTransaction.
    We use the infamously inaccurate vbytes, as usual.

    :param bitcoind: The bitcoind RPC connection, to get the prevouts' value.
    :param tx: The CTransaction to get the feerate of.
    :param prevouts_amount: The sum of the value of all the consumed outputs.

    :return: (int) The feerate of the tx in **sat/vbyte**.
    """
    return (tx_fees(bitcoind, tx, prevouts_amount) + 1) // bitcoind.tx_size(tx)


def fees_to_add(bitcoind, tx, feerate, prevouts_amount):
    current_fees = tx_fees(bitcoind, tx, prevouts_amount)
    current_feerate = tx_feerate(bitcoind, tx, prevouts_amount)
    # Add the estimated size of the new input and output, we assume that we
    # spend a P2WPKH output.
    # Yeah we are not smart. That's a demo.
    new_size = bitcoind.tx_size(tx) + 31 + 67
    new_fees = (current_feerate + feerate) * new_size
    return new_fees - current_fees


def wif_decode(wif_privkey):
    decoded_wif = b58decode_check(wif_privkey)[1:]
    # Compressed ?
    if len(decoded_wif) == 33:
        return decoded_wif[:-1]
    return decoded_wif


def add_input_output(bitcoind, tx, coin, fees):
    """Add another input to the transaction to bump the feerate."""
    coin_amount = Decimal(coin["amount"]) * Decimal(COIN)
    # First get the private key from bitcoind's wallet.
    privkey = CKey(wif_decode(bitcoind.dumpprivkey(coin["address"])))

    # Add the fetched coin as a new input.
    tx.vin.append(CTxIn(COutPoint(lx(coin["txid"]), coin["vout"])))
    # And likely add an output, otherwise all goes to the fees.
    scriptPubKey = CScript([OP_0, Hash160(privkey.pub)])
    if coin_amount > fees + 294:
        # For simplicity, pay to the same script
        tx.vout.append(CTxOut(coin_amount - Decimal(fees), scriptPubKey))
    address = CBitcoinAddress.from_scriptPubKey(scriptPubKey)
    # We only do this once, sign it with ALL
    tx_hash = SignatureHash(address.to_redeemScript(), tx, 1, SIGHASH_ALL,
                            int(coin_amount), SIGVERSION_WITNESS_V0)
    sig = privkey.sign(tx_hash) + bytes([SIGHASH_ALL])
    tx.wit.vtxinwit.append(
        CTxInWitness(CScriptWitness([sig, privkey.pub]))
    )
    return tx


def bump_feerate(bitcoind, tx, feerate_add, prevouts_amount=None):
    """Bump the feerate of a CTransaction.

    :param bitcoind: The bitcoind RPC connection, to access the wallet.
    :param tx: The CTransaction which is to be bumped.
    :param feerate_add: How much to increase the feerate, in sat/vbyte.
    :param prevouts_amount: The sum of the value of all the consumed outputs.

    :return: (CTransaction) The modified transaction.
    """
    # Work on a copy
    vin = [CMutableTxIn.from_txin(txin) for txin in tx.vin]
    vout = [CMutableTxOut.from_txout(txout) for txout in tx.vout]
    wit = CTxWitness([CTxInWitness.from_txinwitness(txinwit)
                      for txinwit in tx.wit.vtxinwit])
    mut_tx = CMutableTransaction(vin, vout, witness=wit,
                                 nLockTime=tx.nLockTime, nVersion=tx.nVersion)

    fees = fees_to_add(bitcoind, mut_tx, feerate_add, prevouts_amount)
    # No smart coin selection here, this is a demo
    for coin in bitcoind.listunspent():
        if coin["amount"] * Decimal(COIN) > fees and coin["spendable"]:
            return add_input_output(bitcoind, mut_tx, coin, fees)
    raise Exception("Could not bump fees, no suitable utxo!")


__all__ = [
    "tx_fees",
    "tx_feerate",
    "bump_feerate",
]
