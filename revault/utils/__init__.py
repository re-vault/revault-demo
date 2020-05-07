from base58 import b58decode_check
from bitcoin.core import (
    CTxIn, COutPoint, CTxWitness, CTxInWitness, CMutableTxIn, CMutableTxOut,
    CMutableTransaction, COIN, b2lx, lx,
)
from bitcoin.core.script import (
    CScriptWitness, SIGHASH_ALL, SIGVERSION_WITNESS_V0, SignatureHash,
)
from bitcoin.wallet import P2WPKHBitcoinAddress, CKey
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
    return int(new_fees - current_fees)


def wif_decode(wif_privkey):
    decoded_wif = b58decode_check(wif_privkey)[1:]
    # Compressed ?
    if len(decoded_wif) == 33:
        return decoded_wif[:-1]
    return decoded_wif


def get_output_index(decoded_tx, sats):
    for output in decoded_tx["vout"]:
        if output["value"] * COIN == sats:
            return decoded_tx["vout"].index(output)

    raise Exception("No such output !")


def add_input(bitcoind, tx, fees):
    """Add another input to the transaction to bump the feerate."""
    # Don't be dust!
    if fees < 294:
        fees = 294

    # Create the first stage transaction
    new_prevout_addr = P2WPKHBitcoinAddress(bitcoind.getnewaddress())
    txid = bitcoind.sendtoaddress(str(new_prevout_addr), fees / COIN)
    out_index = get_output_index(
        bitcoind.getrawtransaction(txid, decode=True), fees
    )
    # Then gather the private key to unlock its output
    privkey = CKey(wif_decode(bitcoind.dumpprivkey(str(new_prevout_addr))))
    # Add the fetched coin as a new input.
    tx.vin.append(CTxIn(COutPoint(lx(txid), out_index)))
    # We only do this once, sign it with ALL
    tx_hash = SignatureHash(new_prevout_addr.to_redeemScript(), tx, 1,
                            SIGHASH_ALL, fees, SIGVERSION_WITNESS_V0)
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
    # FIXME: Add this to python-bitcoinlib
    wit = CTxWitness([CTxInWitness.from_txinwitness(txinwit)
                      for txinwit in tx.wit.vtxinwit])
    mut_tx = CMutableTransaction(vin, vout, witness=wit,
                                 nLockTime=tx.nLockTime, nVersion=tx.nVersion)

    fees = fees_to_add(bitcoind, mut_tx, feerate_add, prevouts_amount)
    if bitcoind.getbalance() * COIN > fees:
        return add_input(bitcoind, mut_tx, fees)

    raise Exception("Could not bump fees, no suitable utxo available!")


__all__ = [
    "tx_fees",
    "tx_feerate",
    "bump_feerate",
]
