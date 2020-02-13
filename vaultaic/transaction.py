import hashlib

from bitcoin.core import CTxOut
from bitcoin.core.script import (
    CScript, OP_CHECKSIG, OP_CHECKSIGVERIFY, OP_SWAP, OP_ADD, OP_DUP, OP_EQUAL,
    OP_EQUALVERIFY, OP_NOP3, OP_IF, OP_ELSE, OP_ENDIF, OP_0,
    OP_2, OP_3, OP_4, OP_6
)

# FIXME: Make Peter Todd accept Kanzure's PRs :(
OP_CHECKSEQUENCEVERIFY = OP_NOP3


def vault_txout(pub1, pub2, pub3, pub4, value):
    """The output of the funding transaction.

    :param pub1: The pubkey of the first stakeholder, as bytes.
    :param pub2: The pubkey of the second stakeholder, as bytes.
    :param pub3: The pubkey of the third stakeholder, as bytes.
    :param pub4: The pubkey of the fourth stakeholder, as bytes.
    :param value: The output value in satoshis.

    :return: A CTxOut paying to a 4of4.
    """
    script = CScript([OP_4, pub1, pub2, pub3, pub4, OP_4])
    p2wsh = CScript([OP_0, hashlib.sha256(script).digest()])
    return CTxOut(value, p2wsh)


def unvault_txout(pub_trader1, pub_trader2, pub1, pub2, pub_server, value):
    """The output of the unvaulting transaction (which spends the funding one).

    This transaction locks coins to server + 2of3 composed of [trader1,
    trader2, stakeholder1] after 6 blocks, or to a 4of4 composed of [trader1,
    trader2, stastakeholder1, stastakeholder2] immediately.

    :param pub_trader1: The pubkey of the first trader, as bytes.
    :param pub_trader2: The pubkey of the second trader, as bytes.
    :param pub1: The pubkey of the first stakeholder, as bytes.
    :param pub2: The pubkey of the second stakeholder, as bytes.
    :param pub_server: The pubkey of the cosigning server, as bytes.
    :param value: The output value in satoshis.

    :return: A CTxOut paying to the script detailed above.
    """
    script = CScript([pub_trader1, OP_CHECKSIG, OP_SWAP, pub_trader2,
                      OP_CHECKSIG, OP_ADD, OP_SWAP, pub1, OP_CHECKSIG, OP_ADD,
                      OP_DUP, OP_3, OP_EQUAL, OP_IF, OP_SWAP, pub2,
                      OP_CHECKSIG, OP_ELSE, OP_2, OP_EQUALVERIFY, pub_server,
                      OP_CHECKSIGVERIFY, OP_6, OP_CHECKSEQUENCEVERIFY,
                      OP_ENDIF])
    p2wsh = CScript([OP_0, hashlib.sha256(script).digest()])
    return CTxOut(value, p2wsh)


def emergency_txout(pub1, pub2, pub3, pub4, value):
    """The "deep vault".

    :param pub1: The offline pubkey of the first stakeholder, as bytes.
    :param pub2: The offline pubkey of the second stakeholder, as bytes.
    :param pub3: The offline pubkey of the third stakeholder, as bytes.
    :param pub4: The offline pubkey of the fourth stakeholder, as bytes.
    :param value: The output value in satoshis.

    :return: A CTxOut paying to a 4of4 of all stakeholers' offline pubkeys.
    """
    # We made it a different transaction just for terminology
    return vault_txout(pub1, pub2, pub3, pub4, value)
