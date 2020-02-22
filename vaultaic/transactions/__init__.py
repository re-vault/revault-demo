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
                    OP_CHECKSIGVERIFY, OP_ELSE, OP_2, OP_EQUALVERIFY,
                    pub_server, OP_CHECKSIGVERIFY, OP_6,
                    OP_CHECKSEQUENCEVERIFY, OP_ENDIF])


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


def spend_vault_txout(vault_txid, vault_vout, privkeys, txout, prev_value):
    """Creates a transaction spending a vault txout.

    Note that this transaction only ever has one input and one output.

    :param vault_txid: The id of the transaction funding the vault.
    :param vault_vout: The index of the vault output in this transaction.
    :param privkeys: A list of the private keys of the four stakeholders to
                     sign the transaction.
    :param txout: The CTxOut to pay to.
    """
    privkeys = [CKey(k) for k in privkeys]
    pubkeys = [k.pub for k in privkeys]
    # A dummy txin to create the transaction hash to sign
    tmp_txin = CTxIn(COutPoint(vault_txid, vault_vout))
    tx = CMutableTransaction([tmp_txin], [txout], nVersion=2)
    tx_hash = SignatureHash(vault_script(pubkeys), tx, vault_vout,
                            SIGHASH_ALL, amount=prev_value,
                            sigversion=SIGVERSION_WITNESS_V0)
    # A signature per pubkey
    sigs = [key.sign(tx_hash) + bytes([SIGHASH_ALL]) for key in privkeys]
    # Spending a P2WSH, so the witness is <unlocking_script> <actual_script>.
    # Here, unlocking_script is the four signatures. Moreover note the empty
    # byte array for the CHECKMULTISIG bug.
    witness_script = [bytes(0), *sigs, vault_script(pubkeys)]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])
    # Make it immutable
    return CTransaction.from_tx(tx)


def unvault_tx(vault_txid, vault_vout, privkeys, pub_server,
               value, prev_value):
    """The transaction which spends from a vault txo.

    :param vault_txid: The id of the transaction funding the vault.
    :param vault_vout: The index of the vault output in this transaction.
    :param privkeys: A list of the private keys of the four stakeholders to
                     sign the transaction. The public keys to reconstruct the
                     script are deduced from them.
                     *The first two keys are assumed to be the traders one !*
    :param pub_server: The pubkey of the cosigning server, as bytes.
    :param value: The output value in satoshis.
    :param prev_value: The prevout value in satoshis.

    :return: The signed unvaulting transaction, a CTransaction.
    """
    pubkeys = [CKey(k).pub for k in privkeys]
    # We spend to the unvaulting script
    txout = unvault_txout(pubkeys, pub_server, value)
    return spend_vault_txout(vault_txid, vault_vout, privkeys, txout,
                             prev_value)


def emergency_vault_tx(vault_txid, vault_vout, privkeys, emer_pubkeys,
                       value, prev_value):
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
    return spend_vault_txout(vault_txid, vault_vout, privkeys, txout,
                             prev_value)


def spend_unvault_txout(unvault_txid, unvault_vout, privkeys,
                        pub_server, txout, prev_value):
    """Creates a transaction spending from an unvault transaction.

    This is the "all stakeholders sign" path of the script, not encumbered by a
    timelock.
    This path is used for both the emergency and cancel transactions.

    :param unvault_txid: The id of the unvaulting transaction.
    :param unvault_vout: The index of the unvault output in this transaction.
    :param privkeys: A list of the private keys of the four stakeholders to
                     sign the transaction.
    :param pub_server: The public key of the cosigning server.
    :param txout: The txo (a CTxOut) to spend the coins to.
    :param prev_value: The prevout's value in satoshis.

    :return: The signed transaction, a CTransaction.
    """
    privkeys = [CKey(k) for k in privkeys]
    pubkeys = [k.pub for k in privkeys]
    # A dummy txin to create the transaction hash to sign
    txin = CTxIn(COutPoint(unvault_txid, unvault_vout))
    tx = CMutableTransaction([txin], [txout], nVersion=2)
    tx_hash = SignatureHash(unvault_script(*pubkeys, pub_server), tx,
                            unvault_vout, SIGHASH_ALL, prev_value,
                            SIGVERSION_WITNESS_V0)
    # A signature per pubkey
    sigs = [key.sign(tx_hash) + bytes([SIGHASH_ALL]) for key in privkeys[::-1]]
    # Spending a P2WSH, so the witness is <unlocking_script> <actual_script>.
    # Here, unlocking_script is the four signatures.
    witness_script = [*sigs, unvault_script(*pubkeys, pub_server)]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])
    # Make it immutable
    return CTransaction.from_tx(tx)


def cancel_unvault_tx(unvault_txid, unvault_vout, privkeys,
                      pub_server, pubkeys, value, prev_value):
    """The transaction which reverts a spend_tx to an "usual" vault, a 4of4.

    :param unvault_txid: The id of the unvaulting transaction.
    :param unvault_vout: The index of the unvault output in this transaction.
    :param privkeys: A list of the private keys of the four stakeholders to
                     sign the transaction.
    :param pub_server: The public key of the cosigning server.
    :param pubkeys: A list of the four public keys of the four stakeholders for
                    the new vault. Can be the same keys.
    :param value: The output value in satoshis.
    :param prev_value: The prevout's value in satoshis.

    :return: The signed unvaulting transaction, a CTransaction.
    """
    # We pay back to a vault
    txout = vault_txout(pubkeys, value)
    return spend_unvault_txout(unvault_txid, unvault_vout, privkeys,
                               pub_server, txout, prev_value)


# FIXME: Make sure the two traders are actually two stakeholders
def emergency_unvault_tx(unvault_txid, unvault_vout, privkeys,
                         pub_server, emer_pubkeys, value, prev_value):
    """The transaction which reverts a spend_tx to the offline 4of4.

    :param unvault_txid: The id of the unvaulting transaction.
    :param unvault_vout: The index of the unvault output in this transaction.
    :param privkeys: A list of the private keys of the four stakeholders to
                     sign the transaction.
    :param pub_server: The public key of the cosigning server.
    :param emer_pubkeys: A list of the four emergency public keys of the four
                         stakeholders.
    :param value: The output value in satoshis.
    :param prev_value: The prevout's value in satoshis.

    :return: The signed unvaulting transaction, a CTransaction.
    """
    # We pay to the emergency script
    txout = emergency_txout(emer_pubkeys, value)
    return spend_unvault_txout(unvault_txid, unvault_vout, privkeys,
                               pub_server, txout, prev_value)


def sign_spend_tx(unvault_txid, unvault_vout, privkeys, pubkeys,
                  pub_server, address, value, prev_value):
    """Signs the transaction which spends the unvault_tx after the relative
    locktime with the given private keys.

    :param unvault_txid: The id of the unvaulting transaction.
    :param unvault_vout: The index of the unvault output in this transaction.
    :param privkeys: A list of the private keys to sign the tx with.
    :param pubkeys: A list of the 4 stakeholders' pubkeys.
    :param pub_server: The public key of the cosigning server.
    :param address: The address to "send the coins to", we'll derive the
                    scriptPubKey out of it.
    :param value: The output value in satoshis.
    :param prev_value: The prevout's value in satoshis.

    :return: A tuple composed of the *unsigned* unvaulting transaction (a
             CMutableTransaction) and the signatures for the pubkeys.
    """
    privkeys = [CKey(k) for k in privkeys]
    txout = CTxOut(value, CBitcoinAddress(address).to_scriptPubKey())
    txin = CTxIn(COutPoint(unvault_txid, unvault_vout), nSequence=6)
    tx = CMutableTransaction([txin], [txout], nVersion=2)
    tx_hash = SignatureHash(unvault_script(*pubkeys, pub_server), tx,
                            unvault_vout, SIGHASH_ALL, prev_value,
                            SIGVERSION_WITNESS_V0)
    sigs = [key.sign(tx_hash) + bytes([SIGHASH_ALL]) for key in privkeys]
    return tx, sigs


def create_spend_tx(tx, pubkeys, serv_pubkey, sigs):
    """Creates the tx spending the unvault_tx after the relative locktime,
    from three signatures.

    :param tx: The unsigned transaction, a CMutableTransaction.
    :param pubkeys: An *ordered* list of the four pubkeys of the stakeholders.
    :param serv_pubkey: The cosigning server pubkey.
    :param sigs: An *ordered* list of *four* bytearrays. Any of the first three
                 can be empty (2of3). The first one is the first trader's
                 signature, the second one the second trader signature, the
                 third one the signature of the stakeholder's pubkey used in
                 the unvaulting script, and the last one the cosigning server's
                 signature.

    :return: The spending transaction, a CTransaction.
    """
    # The sigs are reversed as we request them to be in the same order as the
    # pubkeys to keep the API simple.
    witness_script = [*sigs[::-1], unvault_script(*pubkeys, serv_pubkey)]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])
    # Make it immutable
    return CTransaction.from_tx(tx)


__all__ = [
    "vault_script",
    "vault_txout",
    "unvault_txout",
    "emergency_txout",
    "spend_vault_txout",
    "unvault_tx",
    "emergency_vault_tx",
    "emergency_unvault_tx",
    "sign_spend_tx",
    "create_spend_tx",
]
