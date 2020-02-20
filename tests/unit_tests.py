import bitcoin
import os
import pytest

from bitcoin.core import (
    CTxIn, CTxOut, COutPoint, CTxInWitness, CMutableTransaction, CTxWitness,
    b2x, lx, COIN
)
from bitcoin.rpc import VerifyRejectedError
from bitcoin.core.script import (
    CScriptWitness, SIGHASH_ALL, SIGVERSION_WITNESS_V0, SignatureHash
)
from bitcoin.wallet import CBitcoinAddress, CKey
from decimal import Decimal, getcontext
from fixtures import *  # noqa: F401,F403
from vaultaic.transactions import (
    vault_txout, vault_script, unvault_txout, unvault_script,
)
from vaultaic.utils import empty_signature


bitcoin.SelectParams("regtest")
getcontext().prec = 8


def test_vault_txout(bitcoind):
    """Test that vault_txout() produces a valid output."""
    amount = Decimal("50") - Decimal("500") / Decimal(COIN)
    addresses = [bitcoind.rpc.getnewaddress() for i in range(4)]
    pubkeys = [bytes.fromhex(bitcoind.rpc.getaddressinfo(addr)["pubkey"])
               for addr in addresses]
    privkeys = [bitcoind.rpc.dumpprivkey(addr) for addr in addresses]
    txo = vault_txout(pubkeys, COIN * amount)
    addr = str(CBitcoinAddress.from_scriptPubKey(txo.scriptPubKey))
    # This makes a transaction with only one vout
    txid = bitcoind.pay_to(addr, amount)
    new_amount = amount - Decimal("500") / Decimal(COIN)
    addr = bitcoind.getnewaddress()
    tx = bitcoind.rpc.createrawtransaction([{"txid": txid, "vout": 0}],
                                           [{addr: float(new_amount)}])
    tx = bitcoind.rpc.signrawtransactionwithkey(tx, privkeys, [
        {
            "txid": txid,
            "vout": 0,  # no change output
            "scriptPubKey": b2x(txo.scriptPubKey),
            "witnessScript": b2x(vault_script(pubkeys)),
            "amount": str(amount)
         }
    ])
    bitcoind.send_tx(tx["hex"])
    assert bitcoind.has_utxo(addr)


def test_unvault_txout(bitcoind):
    """Test that unvault_txout() produces a valid and conform txo.

    Note that we use python-bitcoinlib for this one, as
    signrawtransactionwithkey is (apparently?) not happy dealing with exotic
    scripts.
    Note also that bitcoinlib's API uses sats, while bitcoind's one uses BTC..
    """
    amount = 50 * COIN - 500
    # The stakeholders
    stk_privkeys = [CKey(os.urandom(32)) for i in range(4)]
    stk_pubkeys = [k.pub for k in stk_privkeys]
    # The cosigning server
    serv_privkey = CKey(os.urandom(32))
    # First, pay to the unvault tx script
    txo = unvault_txout(stk_pubkeys,
                        serv_privkey.pub, amount)
    txo_addr = str(CBitcoinAddress.from_scriptPubKey(txo.scriptPubKey))
    txid = bitcoind.pay_to(txo_addr, Decimal(amount) / Decimal(COIN))
    # We can spend it immediately if all stakeholders sign (emergency or cancel
    # tx)
    txin = CTxIn(COutPoint(lx(txid), 0))
    amount_min_fees = amount - 500
    addr = bitcoind.getnewaddress()
    new_txo = CTxOut(amount_min_fees,
                     CBitcoinAddress(addr).to_scriptPubKey())
    tx = CMutableTransaction([txin], [new_txo], nVersion=2)
    tx_hash = SignatureHash(unvault_script(*stk_pubkeys, serv_privkey.pub), tx,
                            0, SIGHASH_ALL, amount, SIGVERSION_WITNESS_V0)
    sigs = [key.sign(tx_hash) + bytes([SIGHASH_ALL])
            for key in stk_privkeys[::-1]]  # Note the reverse here
    witness_script = [*sigs,
                      unvault_script(*stk_pubkeys, serv_privkey.pub)]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])
    bitcoind.send_tx(b2x(tx.serialize()))
    assert bitcoind.has_utxo(addr)

    # If two out of three stakeholders sign, we need the signature from the
    # cosicosigning server and we can't spend it before 6 blocks (csv).
    # Pay back to the unvault tx script
    txo = unvault_txout(stk_pubkeys,
                        serv_privkey.pub, amount)
    txo_addr = str(CBitcoinAddress.from_scriptPubKey(txo.scriptPubKey))
    txid = bitcoind.pay_to(txo_addr, Decimal(amount) / Decimal(COIN))
    # Reconstruct the transaction but with only two stakeholders signatures
    txin = CTxIn(COutPoint(lx(txid), 0), nSequence=6)
    amount_min_fees = amount - 500
    addr = bitcoind.getnewaddress()
    new_txo = CTxOut(amount_min_fees,
                     CBitcoinAddress(addr).to_scriptPubKey())
    tx = CMutableTransaction([txin], [new_txo], nVersion=2)
    tx_hash = SignatureHash(unvault_script(*stk_pubkeys, serv_privkey.pub), tx,
                            0, SIGHASH_ALL, amount, SIGVERSION_WITNESS_V0)
    # The cosigning server
    sigs = [serv_privkey.sign(tx_hash) + bytes([SIGHASH_ALL])]
    # We fail the third CHECKSIG !!
    sigs += [empty_signature()]
    sigs += [key.sign(tx_hash) + bytes([SIGHASH_ALL])
             for key in stk_privkeys[::-1][2:]]  # Just the first two
    witness_script = [*sigs,
                      unvault_script(*stk_pubkeys, serv_privkey.pub)]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])
    # Relative locktime !
    for i in range(5):
        with pytest.raises(VerifyRejectedError, match="non-BIP68-final"):
            bitcoind.send_tx(b2x(tx.serialize()))
        bitcoind.generate_block(1)
    # It's been 6 blocks now
    bitcoind.send_tx(b2x(tx.serialize()))
    assert bitcoind.has_utxo(addr)
