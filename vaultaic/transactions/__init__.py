import hashlib

from bitcoin.core import (
    CTxOut, CTxIn, CTxInWitness, CTxWitness, CMutableTransaction, CTransaction,
    COutPoint,
)
from bitcoin.core.script import (
    CScript, OP_CHECKSIG, OP_CHECKSIGVERIFY, OP_CHECKMULTISIG, OP_SWAP, OP_ADD,
    OP_DUP, OP_EQUAL, OP_EQUALVERIFY, OP_NOP3, OP_IF, OP_ELSE, OP_ENDIF, OP_0,
    OP_2, OP_3, OP_4, OP_6, SignatureHash, SIGHASH_ALL, SIGVERSION_WITNESS_V0,
    CScriptWitness
)
from bitcoin.wallet import CKey, CBitcoinAddress


# FIXME: Make Peter Todd accept Kanzure's PRs :(
OP_CHECKSEQUENCEVERIFY = OP_NOP3


def vault_script(pubkeys):
    """The locking script of the funding transaction (not the P2WSH!).

    :param pubkeys: A list containing the pubkey of each stakeholder, as bytes.

    :return: A CScript representing a 4of4.
    """
    return CScript([OP_4, *pubkeys, OP_4, OP_CHECKMULTISIG])


def vault_txout(pubkeys, value):
    """The output of the funding transaction.

    :param pubkeys: A list containing the pubkey of each stakeholder, as bytes.
    :param value: The output value in satoshis.

    :return: A CTxOut paying to a 4of4.
    """
    script = vault_script(pubkeys)
    p2wsh = CScript([OP_0, hashlib.sha256(script).digest()])
    return CTxOut(value, p2wsh)


def unvault_script(pub_trader1, pub_trader2, pub1, pub2, pub_server):
    return CScript([pub_trader1, OP_CHECKSIG, OP_SWAP, pub_trader2,
                    OP_CHECKSIG, OP_ADD, OP_SWAP, pub1, OP_CHECKSIG, OP_ADD,
                    OP_DUP, OP_3, OP_EQUAL, OP_IF, OP_SWAP, pub2,
                    OP_CHECKSIG, OP_ELSE, OP_2, OP_EQUALVERIFY, pub_server,
                    OP_CHECKSIGVERIFY, OP_6, OP_CHECKSEQUENCEVERIFY,
                    OP_ENDIF])


# FIXME: Make sure the two traders are part of the stakeholders !!
def unvault_txout(pubkeys, pub_server, value):
    """The output of the unvaulting transaction (which spends the funding one).

    This transaction locks coins to server + 2of3 composed of [trader1,
    trader2, stakeholder1] after 6 blocks, or to a 4of4 composed of [trader1,
    trader2, stastakeholder1, stastakeholder2] immediately.

    :param pubkeys: The pubkeys of the 4 stakeholders, as bytes.
    :param pub_server: The pubkey of the cosigning server, as bytes.
    :param value: The output value in satoshis.

    :return: A CTxOut paying to the script detailed above.
    """
    script = unvault_script(*pubkeys, pub_server)
    p2wsh = CScript([OP_0, hashlib.sha256(script).digest()])
    return CTxOut(value, p2wsh)


def emergency_txout(pubkeys, value):
    """The "deep vault".

    :param pubkeys: A list containing the offline pubkey of each of the
                    stakeholders, as bytes.
    :param value: The output value in satoshis.

    :return: A CTxOut paying to a 4of4 of all stakeholers' offline pubkeys.
    """
    # We made it a different transaction just for terminology
    return vault_txout(pubkeys, value)


def spend_vault_txout(vault_txid, vault_vout, privkeys, txout):
    """Creates a transaction spending a vault txout.

    Note that this transaction only ever has one input and one output.

    :param vault_txid: The id of the transaction funding the vault.
    :param vault_vout: The index of the vault output in this transaction.
    :param privkeys: A list of the private keys of the four stakeholders to
                     sign the transaction.
    :param txout: The CTxOut to pay to.
    """
    privkeys = [CKey(k) for k in privkeys]
    # A dummy txin to create the transaction hash to sign
    tmp_txin = CTxIn(COutPoint(vault_txid, vault_vout))
    tx = CMutableTransaction([tmp_txin], [txout])
    tx_hash = SignatureHash(txout.scriptPubKey, tx, vault_vout,
                            SIGHASH_ALL, amount=txout.nValue,
                            sigversion=SIGVERSION_WITNESS_V0)
    # A signature per pubkey
    sigs = [key.sign(tx_hash) + bytes([SIGHASH_ALL]) for key in privkeys]
    # Spending a P2WSH, so the witness is <unlocking_script> <actual_script>.
    # Here, unlocking_script is the four signatures.
    witness_script = [*sigs, CScript([OP_4, *[k.pub for k in privkeys], OP_4])]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])
    # Make it immutable
    return CTransaction.from_tx(tx)


def unvault_tx(vault_txid, vault_vout, privkeys, pub_trader1,
               pub_trader2, pub1, pub2, pub_server, value):
    """The transaction which spends from a vault txo.

    :param vault_txid: The id of the transaction funding the vault.
    :param vault_vout: The index of the vault output in this transaction.
    :param privkeys: A list of the private keys of the four stakeholders to
                     sign the transaction.
    :param pub_trader1: The pubkey of the first trader, as bytes.
    :param pub_trader2: The pubkey of the second trader, as bytes.
    :param pub1: The pubkey of the first stakeholder, as bytes.
    :param pub2: The pubkey of the second stakeholder, as bytes.
    :param pub_server: The pubkey of the cosigning server, as bytes.
    :param value: The output value in satoshis.

    :return: The signed unvaulting transaction, a CTransaction.
    """
    # We spend to the unvaulting script
    txout = unvault_txout(pub_trader1, pub_trader2, pub1, pub2,
                          pub_server, value)
    return spend_vault_txout(vault_txid, vault_vout, privkeys, txout)


def emergency_vault_tx(vault_txid, vault_vout, privkeys, emer_pubkeys, value):
    """The transaction which moves a vault's coins to the offline 4of4.

    :param vault_txid: The id of the transaction funding the vault.
    :param vault_vout: The index of the vault output in this transaction.
    :param privkeys: A list of the private keys of the four stakeholders to
                     sign the transaction.
    :param emer_pubkeys: A list of the four emergency public keys of the four
                         stakeholders.
    :param value: The output value in satoshis.

    :return: The signed emrgency transaction, a CTransaction.
    """
    # We pay to the emergency script
    txout = emergency_txout(emer_pubkeys, value)
    return spend_vault_txout(vault_txid, vault_vout, privkeys, txout)


# FIXME: Make sure the two traders are actually two stakeholders
def emergency_unvault_tx(unvault_txid, unvault_vout, privkeys,
                         pub_server, emer_pubkeys, value):
    """The transaction which reverts a spend_tx to the offline 4of4.

    :param unvault_txid: The id of the unvaulting transaction.
    :param unvault_vout: The index of the unvault output in this transaction.
    :param privkeys: A list of the private keys of the four stakeholders to
                     sign the transaction.
    :param pub_server: The public key of the cosigning server.
    :param emer_pubkeys: A list of the four emergency public keys of the four
                         stakeholders.
    :param value: The output value in satoshis.

    :return: The signed unvaulting transaction, a CTransaction.
    """
    privkeys = [CKey(k) for k in privkeys]
    # We pay to the emergency script
    txout = emergency_txout(emer_pubkeys, value)
    # A dummy txin to create the transaction hash to sign
    tmp_txin = CTxIn(COutPoint(unvault_txid, unvault_vout))
    tx = CMutableTransaction([tmp_txin], [txout])
    tx_hash = SignatureHash(txout.scriptPubKey, tx, unvault_vout,
                            SIGHASH_ALL, amount=txout.nValue,
                            sigversion=SIGVERSION_WITNESS_V0)
    # A signature per pubkey
    sigs = [key.sign(tx_hash) + bytes([SIGHASH_ALL]) for key in privkeys]
    # Spending a P2WSH, so the witness is <unlocking_script> <actual_script>.
    # Here, unlocking_script is the four signatures.
    witness_script = [*sigs,
                      unvault_script(*[k.pub for k in privkeys], pub_server)]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])
    # Make it immutable
    return CTransaction.from_tx(tx)


def spend_unvault_tx(unvault_txid, unvault_vout, privkeys, pubkeys,
                     pub_server, address, value):
    """The transaction which spends the unvault_tx after the relative locktime.

    Note that we logically cannot entirely sign this transaction, as we are
    from the PoV of a stakeholder and that this transaction needs the signature
    of the co-signing server.

    :param unvault_txid: The id of the unvaulting transaction.
    :param unvault_vout: The index of the unvault output in this transaction.
    :param privkeys: A list of the private keys of two of the three
                     stakeholders in the 2of3.
    :param pubkeys: A list of the 4 stakeholders' pubkeys.
    :param pub_server: The public key of the cosigning server.
    :param address: The address to "send the coins to", we'll derive the
                    scriptPubKey out of it.
    :param value: The output value in satoshis.

    :return: The partially signed unvaulting transaction,
             a CMutableTransaction.
    """
    privkeys = [CKey(k) for k in privkeys]
    txout = CTxOut(value, CBitcoinAddress(address).to_scriptPubKey())
    # A dummy txin to create the transaction hash to sign
    tmp_txin = CTxIn(COutPoint(unvault_txid, unvault_vout), nSequence=6)
    tx = CMutableTransaction([tmp_txin], [txout])
    tx_hash = SignatureHash(txout.scriptPubKey, tx, unvault_vout,
                            SIGHASH_ALL, amount=txout.nValue,
                            sigversion=SIGVERSION_WITNESS_V0)
    # A signature per pubkey
    sigs = [key.sign(tx_hash) + bytes([SIGHASH_ALL]) for key in privkeys]
    # Spending a P2WSH, so the witness is <unlocking_script> <actual_script>.
    # Here, part of the unlocking_script is the two signatures.
    witness_script = [*sigs, unvault_script(*pubkeys, pub_server)]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])
    return tx


__all__ = [
    "vault_script",
    "vault_txout",
    "unvault_txout",
    "emergency_txout",
    "spend_vault_txout",
    "unvault_tx",
    "emergency_vault_tx",
    "emergency_unvault_tx",
    "spend_unvault_tx",
]
