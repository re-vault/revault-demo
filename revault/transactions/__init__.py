import hashlib

from bitcoin.core import (
    CTxOut, CTxIn, CTxInWitness, CTxWitness, CMutableTransaction, CTransaction,
    COutPoint,
)
from bitcoin.core.script import (
    CScript, OP_CHECKSIG, OP_CHECKSIGVERIFY, OP_CHECKMULTISIG, OP_SWAP, OP_ADD,
    OP_DUP, OP_EQUAL, OP_EQUALVERIFY, OP_CHECKSEQUENCEVERIFY, OP_DROP,
    OP_IF, OP_ELSE, OP_ENDIF, OP_0, OP_2, OP_3, OP_4, OP_6, SignatureHash,
    SIGHASH_ALL, SIGVERSION_WITNESS_V0, CScriptWitness
)
from bitcoin.wallet import CKey, CBitcoinAddress


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
                    OP_DUP, OP_3, OP_EQUAL, OP_IF, OP_SWAP,
                    pub2, OP_CHECKSIGVERIFY, OP_ELSE, OP_2, OP_EQUALVERIFY,
                    pub_server, OP_CHECKSIGVERIFY, OP_6,
                    OP_CHECKSEQUENCEVERIFY, OP_ENDIF])


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


def emergency_script(pubkeys):
    # A locktime of a month
    # >>> 31 * 24 * 6
    return CScript([4464, OP_CHECKSEQUENCEVERIFY, OP_DROP, OP_4,
                    *pubkeys, OP_4, OP_CHECKMULTISIG])


def emergency_txout(pubkeys, value):
    """The "deep vault". Different pubkeys, and a big timelock.

    :param pubkeys: A list containing the offline pubkey of each of the
                    stakeholders, as bytes.
    :param value: The output value in satoshis.

    :return: A CTxOut paying to a 4of4 of all stakeholers' offline pubkeys
             after approximatively a month.
    """
    script = emergency_script(pubkeys)
    p2wsh = CScript([OP_0, hashlib.sha256(script).digest()])
    return CTxOut(value, p2wsh)


def create_spend_vault_txout(vault_txid, vault_vout, txout):
    """Creates a transaction spending a vault txout.

    Note that this transaction only ever has one input and one output.

    :param vault_txid: The id of the transaction funding the vault, as bytes.
    :param vault_vout: The index of the vault output in this transaction.
    :param txout: The CTxOut to pay to.

    :return: The *unsigned* transaction, a CMutableTransaction.
    """
    tmp_txin = CTxIn(COutPoint(vault_txid, vault_vout))
    return CMutableTransaction([tmp_txin], [txout], nVersion=2)


def sign_spend_vault_txout(tx, pubkeys, prev_value, privkeys):
    """Signs a transaction spending a vault txout it with the given private keys.

    :param tx: The CMutableTransaction to sign.
    :param pubkeys: A list of each stakeholder's pubkey.
    :param prev_value: The value of the vault txout we spend.
    :param privkeys: A list of the private keys of the four stakeholders to
                     sign the transaction.

    :return: The signatures in the same order as the private keys.
    """
    tx_hash = SignatureHash(vault_script(pubkeys), tx, 0,
                            SIGHASH_ALL, amount=prev_value,
                            sigversion=SIGVERSION_WITNESS_V0)
    # A signature per pubkey
    sigs = [CKey(key).sign(tx_hash) + bytes([SIGHASH_ALL]) for key in privkeys]
    return sigs


def form_spend_vault_txout(tx, pubkeys, sigs):
    """Forms the final transaction spending a vault txout.

    :param tx: The unsigned transaction, as a CMutableTransaction.
    :param pubkeys: A list containing the pubkey of each of the four
                    stakeholders.
    :param sigs: A list of the four signatures for the four pubkeys, in the
                 same order.

    :return: The immutable CTransaction.
    """
    # Spending a P2WSH, so the witness is <unlocking_script> <actual_script>.
    # Here, unlocking_script is the four signatures. Moreover note the empty
    # byte array for the CHECKMULTISIG bug.
    witness_script = [bytes(0), *sigs, vault_script(pubkeys)]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])
    # Make it immutable
    return CTransaction.from_tx(tx)


def create_unvault_tx(vault_txid, vault_vout, pubkeys, pub_server, value):
    """Creates the unvaulting transaction.

    :param vault_txid: The id of the transaction funding the vault.
    :param vault_vout: The index of the vault output in this transaction.
    :param pubkeys: A list containing the public key of each stakeholder.
    :param pub_server: The pubkey of the cosigning server, as bytes.
    :param value: The output value in satoshis.

    :return: The unsigned unvaulting transaction, a CMutableTransaction.
    """
    txout = unvault_txout(pubkeys, pub_server, value)
    return create_spend_vault_txout(vault_txid, vault_vout, txout)


def sign_unvault_tx(tx, pubkeys, prev_value, privkeys):
    """Signs the unvaulting transaction.

    :param vault_txid: The id of the transaction funding the vault.
    :param pubkeys: A list containing the public key of each stakeholder.
    :param prev_value: The vault output (previout output) value in satoshis.
    :param privkeys: A list of the private keys to sign the transaction with.

    :return: The signatures in the same order as the given privkeys.
    """
    return sign_spend_vault_txout(tx, pubkeys, prev_value, privkeys)


def form_unvault_tx(tx, pubkeys, sigs):
    """Forms the unvault transaction out of the signatures.

    :param tx: The unsigned unvault transaction.
    :param pubkeys: A list containing the public key of each stakeholder.
    :param sigs: A list of the signatures in the same order as the public
                 keys.

    :return: The signed unvaulting transaction, a CTransaction.
    """
    return form_spend_vault_txout(tx, pubkeys, sigs)


def create_emergency_vault_tx(vault_txid, vault_vout, value, emer_pubkeys):
    """Creates the transaction which moves a vault's coins to the offline 4of4.

    :param vault_txid: The id of the transaction funding the vault, as bytes.
    :param vault_vout: The index of the vault output in this transaction.
    :param value: The output value in satoshis.
    :param emer_pubkeys: A list of the four emergency public keys of the four
                         stakeholders.

    :return: The unsigned emergency transaction, a CMutableTransaction.
    """
    txout = emergency_txout(emer_pubkeys, value)
    return create_spend_vault_txout(vault_txid, vault_vout, txout)


def sign_emergency_vault_tx(tx, pubkeys, prev_value, privkeys):
    """Signs the transaction which moves a vault's coins to the offline 4of4.

    :param vault_txid: The id of the transaction funding the vault, as bytes.
    :param pubkeys: A list containing the public key of each stakeholder.
    :param prev_value: The vault output (previout output) value in satoshis.
    :param privkeys: A list of the private keys of the four stakeholders to
                     sign the transaction.

    :return: A tuple, the *unsigned* emergency transaction and the signatures.
    """
    return sign_spend_vault_txout(tx, pubkeys, prev_value, privkeys)


def form_emergency_vault_tx(tx, pubkeys, sigs):
    """Form the emergency transaction out of the signatures.

    :param tx: The unsigned unvault transaction.
    :param pubkeys: A list containing the public key of each stakeholder.
    :param sigs: A list of the signatures in the same order than the public
                 keys.

    :return: The signed emergency transaction, a CTransaction.
    """
    return form_spend_vault_txout(tx, pubkeys, sigs)


def create_unvault_spend(unvault_txid, unvault_vout, txout):
    """Creates a transaction spending from an unvault transaction.

    :param unvault_txid: The id of the unvaulting transaction.
    :param unvault_vout: The index of the unvault output in this transaction.
    :param txout: The txo (a CTxOut) to spend the coins to.

    :return: The unsigned transaction, a CMutableTransaction.
    """
    txin = CTxIn(COutPoint(unvault_txid, unvault_vout))
    return CMutableTransaction([txin], [txout], nVersion=2)


def sign_unvault_spend(tx, privkeys, pubkeys, pub_server, prev_value):
    """Signs a transaction spending from an unvault transaction.

    This is the "all stakeholders sign" path of the script, not encumbered by a
    timelock.
    This path is used for both the emergency and cancel transactions.

    :param tx: The unsigned transaction, a CMutableTransaction.
    :param privkeys: The private keys to sign the transaction with (a list).
    :param pubkeys: The pubkeys of the stakeholders.
    :param pub_server: The pubkey of the cosigning server.
    :param prev_value: The prevout's value in satoshis.

    :return: The signatures for the provided privkeys (a list).
    """
    tx_hash = SignatureHash(unvault_script(*pubkeys, pub_server), tx,
                            0, SIGHASH_ALL, prev_value,
                            SIGVERSION_WITNESS_V0)
    return [CKey(key).sign(tx_hash) + bytes([SIGHASH_ALL])
            for key in privkeys]


def form_unvault_spend(tx, sigs, pubkeys, pub_server):
    """Forms the transaction spending from an unvault using fours signatures.

    :param tx: The unsigned transaction, a CMutableTransaction.
    :param sigs: The list of the four signatures in the same order as the
                 following pubkeys.
    :param pubkeys: The pubkeys of the stakeholders, to form the script.
    :param pub_server: The pubkey of the cosigning server, to form the script.

    :return: The immutable signed transaction, a CTransaction.
    """
    # Note that we use 4 sigs, but no CHECKMULTISIG, so no empty byte array at
    # the begining of this one!
    witness_script = [*sigs[::-1], unvault_script(*pubkeys, pub_server)]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])
    # Make it immutable
    return CTransaction.from_tx(tx)


def create_cancel_tx(unvault_txid, unvault_vout, pubkeys, value):
    """The transaction which reverts a spend_tx to an "usual" vault, a 4of4.

    :param unvault_txid: The id of the unvaulting transaction.
    :param unvault_vout: The index of the unvault output in this transaction.
    :param pubkeys: A list of the four public keys of the four stakeholders for
                    the new vault. Can be the same keys.
    :param value: The amount of the new vault.

    :return: The unsigned transaction, a CMutableTransaction.
    """
    # We pay back to a vault
    txout = vault_txout(pubkeys, value)
    return create_unvault_spend(unvault_txid, unvault_vout, txout)


def sign_cancel_tx(tx, privkeys, pubkeys, pub_server, prev_value):
    """Signs the cancel transaction with the given privkeys.

    :param tx: The unsigned transaction, a CMutableTransaction.
    :param privkeys: The private keys to sign the transaction with (a list).
    :param pubkeys: The pubkeys of the stakeholders.
    :param pub_server: The pubkey of the cosigning server.
    :param prev_value: The prevout's value in satoshis.

    :return: The signatures for the provided privkeys (a list).
    """
    return sign_unvault_spend(tx, privkeys, pubkeys, pub_server, prev_value)


def form_cancel_tx(tx, sigs, pubkeys, pub_server):
    """Forms the cancel transaction using fours signatures.

    :param tx: The unsigned transaction, a CMutableTransaction.
    :param sigs: The list of the four signatures in the same order as the
                 following pubkeys.
    :param pubkeys: The pubkeys of the stakeholders, to form the script.
    :param pub_server: The pubkey of the cosigning server, to form the script.

    :return: The immutable signed transaction, a CTransaction.
    """
    return form_unvault_spend(tx, sigs, pubkeys, pub_server)


def create_emer_unvault_tx(unvault_txid, unvault_vout, emer_pubkeys, value):
    """Create the transaction which reverts a spend_tx to the offline 4of4.

    :param unvault_txid: The id of the unvaulting transaction.
    :param unvault_vout: The index of the unvault output in this transaction.
    :param emer_pubkeys: A list of the four emergency public keys of the four
                         stakeholders.
    :param value: The output value in satoshis.

    :return: The unsigned unvaulting transaction, a CMutableTransaction.
    """
    # We pay to the emergency script
    txout = emergency_txout(emer_pubkeys, value)
    return create_unvault_spend(unvault_txid, unvault_vout, txout)


def sign_emer_unvault_tx(tx, privkeys, pubkeys, pub_server, prev_value):
    """Sign the transaction which reverts a spend_tx to the offline 4of4.

    :param tx: The unsigned transaction, a CMutableTransaction.
    :param privkeys: A list of the private keys to sign the transaction with.
    :param pubkeys: A list of all the stakeholders' vault public keys.
    :param pub_server: The public key of the cosigning server.
    :param prev_value: The prevout's value in satoshis.

    :return: A list of the signature for each provided private key.
    """
    return sign_unvault_spend(tx, privkeys, pubkeys, pub_server, prev_value)


def form_emer_unvault_tx(tx, sigs, pubkeys, pub_server):
    """Forms the transaction which reverts a spend_tx to the offline 4of4.

    :param tx: The unsigned transaction, a CMutableTransaction.
    :param sigs: The list of the four signatures in the same order as the
                 following pubkeys.
    :param pubkeys: The pubkeys of the stakeholders, to form the script.
    :param pub_server: The pubkey of the cosigning server, to form the script.

    :return: The immutable signed transaction, a CTransaction.
    """
    return form_unvault_spend(tx, sigs, pubkeys, pub_server)


def create_spend_tx(unvault_txid, unvault_vout, addresses):
    """Create the transaction which spends the unvault_tx after the relative
    locktime with the given private keys.

    :param unvault_txid: The id of the unvaulting transaction.
    :param unvault_vout: The index of the unvault output in this transaction.
    :param addresses: A dictionary containing address as keys and amount to
                      send in sats as value.

    :return: The unsigned transaction, a CMutableTransaction.
    """
    txouts = [CTxOut(value, CBitcoinAddress(address).to_scriptPubKey())
              for address, value in addresses.items()]
    txin = CTxIn(COutPoint(unvault_txid, unvault_vout), nSequence=6)
    return CMutableTransaction([txin], txouts, nVersion=2)


def sign_spend_tx(tx, privkeys, pubkeys, pub_server, prev_value):
    """Signs the transaction which spends the unvault_tx after the relative
    locktime with the given private keys.

    :param tx: The unsigned transaction, a CMutableTransaction.
    :param privkeys: A list of the private keys to sign the tx with.
    :param pubkeys: A list of the 4 stakeholders' pubkeys, to form the script.
    :param pub_server: The public key of the cosigning server, to form the
                       script.
    :param prev_value: The prevout's value in satoshis.

    :return: A list of the signature for each given private key.
    """
    privkeys = [CKey(k) for k in privkeys]
    tx_hash = SignatureHash(unvault_script(*pubkeys, pub_server), tx,
                            0, SIGHASH_ALL, prev_value, SIGVERSION_WITNESS_V0)
    sigs = [key.sign(tx_hash) + bytes([SIGHASH_ALL]) for key in privkeys]
    return sigs


def form_spend_tx(tx, pubkeys, serv_pubkey, sigs):
    """Forms the tx spending the unvault_tx after the relative locktime,
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


def get_transaction_size(tx):
    """Get the size of a CTransaction.

    :param tx: The CTransaction to get the size of.

    :return: (int) The transaction size **in vbytes**
    """
    # FIXME: introduce weights into python-bitcoinlib
    return len(tx.serialize())


__all__ = [
    "vault_script",
    "vault_txout",
    "unvault_txout",
    "emergency_txout",
    "spend_vault_txout",
    "create_emergency_vault_tx",
    "sign_emergency_vault_tx",
    "form_emergency_vault_tx",
    "create_unvault_tx",
    "sign_unvault_tx",
    "form_unvault_tx",
    "create_cancel_tx",
    "sign_cancel_tx",
    "form_cancel_tx",
    "create_emer_unvault_tx",
    "sign_emer_unvault_tx",
    "form_emer_unvault_tx",
    "create_spend_tx",
    "sign_spend_tx",
    "form_spend_tx",
    "get_transaction_size",
]
