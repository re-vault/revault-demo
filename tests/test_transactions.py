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
from revault.transactions import (
    vault_txout, vault_script, unvault_txout, unvault_script, emergency_txout,
    emergency_script, create_unvault_tx, sign_unvault_tx, form_unvault_tx,
    create_emergency_vault_tx, sign_emergency_vault_tx,
    form_emergency_vault_tx, create_cancel_tx, sign_cancel_tx, form_cancel_tx,
    create_emer_unvault_tx, sign_emer_unvault_tx, form_emer_unvault_tx,
    create_spend_tx, sign_spend_tx, form_spend_tx,
)
from revault.utils import empty_signature


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
    amount_for_bitcoind = float(Decimal(amount) / Decimal(COIN))
    txid = bitcoind.pay_to(txo_addr, amount_for_bitcoind)
    # We can spend it immediately if all stakeholders sign (emergency or cancel
    # tx)
    txin = CTxIn(COutPoint(lx(txid), 0))
    amount_min_fees = amount - 500
    addr = bitcoind.getnewaddress()
    new_txo = CTxOut(amount_min_fees,
                     CBitcoinAddress(addr).to_scriptPubKey())
    tx = CMutableTransaction([txin], [new_txo], nVersion=2)
    # We can't test the signing against bitcoind, but we can at least test the
    # transaction format
    bitcoind_tx = bitcoind.rpc.createrawtransaction([
        {"txid": txid, "vout": 0}
    ], [
        {addr: float(Decimal(amount_min_fees) / Decimal(COIN))}
    ])
    assert b2x(tx.serialize()) == bitcoind_tx
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
    txid = bitcoind.pay_to(txo_addr, amount_for_bitcoind)
    # Reconstruct the transaction but with only two stakeholders signatures
    txin = CTxIn(COutPoint(lx(txid), 0), nSequence=6)
    amount_min_fees = amount - 500
    addr = bitcoind.getnewaddress()
    new_txo = CTxOut(amount_min_fees,
                     CBitcoinAddress(addr).to_scriptPubKey())
    tx = CMutableTransaction([txin], [new_txo], nVersion=2)
    # We can't test the signing against bitcoind, but we can at least test the
    # transaction format
    bitcoind_tx = bitcoind.rpc.createrawtransaction([
        {"txid": txid, "vout": 0, "sequence": 6}
    ], [
        {addr: float(Decimal(amount_min_fees) / Decimal(COIN))}
    ])
    assert b2x(tx.serialize()) == bitcoind_tx
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


def test_emergency_txout(bitcoind):
    """Test mostly the emergency tx locktime"""
    amount = Decimal("50") - Decimal("500") / Decimal(COIN)
    privkeys = [CKey(os.urandom(32)) for _ in range(4)]
    pubkeys = [k.pub for k in privkeys]
    txo = emergency_txout(pubkeys, COIN * amount)
    addr = str(CBitcoinAddress.from_scriptPubKey(txo.scriptPubKey))
    # This makes a transaction with only one vout
    txid = bitcoind.pay_to(addr, amount)
    new_amount = amount - Decimal("500") / Decimal(COIN)
    addr = bitcoind.getnewaddress()
    txin = CTxIn(COutPoint(lx(txid), 0), nSequence=4464)
    txout = CTxOut(new_amount * COIN, CBitcoinAddress(addr).to_scriptPubKey())
    tx = CMutableTransaction([txin], [txout], nVersion=2)
    tx_hash = SignatureHash(emergency_script(pubkeys), tx, 0, SIGHASH_ALL,
                            int(amount * COIN), SIGVERSION_WITNESS_V0)
    sigs = [k.sign(tx_hash) + bytes([SIGHASH_ALL]) for k in privkeys]
    witness_script = [bytes(0), *sigs, emergency_script(pubkeys)]
    tx.wit = CTxWitness([CTxInWitness(CScriptWitness(witness_script))])
    # 1 month of locktime
    bitcoind.generate_block(4464 - 2)
    with pytest.raises(VerifyRejectedError, match="non-BIP68-final"):
        bitcoind.send_tx(tx.serialize().hex())
    bitcoind.generate_block(1)
    bitcoind.send_tx(tx.serialize().hex())
    assert bitcoind.has_utxo(addr)


def send_vault_tx(bitcoind, pubkeys, amount):
    """Creates a vault transaction for {amount} *sats*"""
    txo = vault_txout(pubkeys, amount)
    addr = str(CBitcoinAddress.from_scriptPubKey(txo.scriptPubKey))
    # This makes a transaction with only one vout
    amount_for_bitcoind = Decimal(amount) / Decimal(COIN)
    txid = bitcoind.pay_to(addr, amount_for_bitcoind)
    return txid


def test_unvault_tx(bitcoind):
    """This tests the unvault_tx() function."""
    # The stakeholders, the first two are the traders.
    stk_privkeys = [os.urandom(32) for i in range(4)]
    stk_pubkeys = [CKey(k).pub for k in stk_privkeys]
    # The co-signing server, required by the spend tx
    serv_privkey = CKey(os.urandom(32))
    serv_pubkey = serv_privkey.pub
    # Create the transaction funding the vault
    amount = 50 * COIN - 500
    vault_txid = lx(send_vault_tx(bitcoind, stk_pubkeys, amount))
    # Create the transaction spending from the vault
    amount_min_fees = amount - 500
    unvtx = create_unvault_tx(vault_txid, 0, stk_pubkeys, serv_pubkey,
                              amount_min_fees)
    assert len(unvtx.vout) == 1
    # Simulate that each stakeholder sign the transaction separately
    sigs = [sign_unvault_tx(unvtx, stk_pubkeys, amount, [k])[0]
            for k in stk_privkeys]
    unvtx = form_unvault_tx(unvtx, stk_pubkeys, sigs)
    bitcoind.send_tx(b2x(unvtx.serialize()))


def test_emergency_vault_tx(bitcoind):
    """This tests the emergency_vault_tx() function."""
    # The stakeholders, the first two are the traders.
    stk_privkeys = [os.urandom(32) for i in range(4)]
    stk_pubkeys = [CKey(k).pub for k in stk_privkeys]
    # The stakeholders emergency keys
    emer_privkeys = [os.urandom(32) for i in range(4)]
    emer_pubkeys = [CKey(k).pub for k in emer_privkeys]
    # Create the transaction funding the vault
    amount = 50 * COIN - 500
    vault_txid = lx(send_vault_tx(bitcoind, stk_pubkeys, amount))
    # Create the emergency transaction spending from the vault
    amount_min_fees = amount - 500
    emer_tx = create_emergency_vault_tx(vault_txid, 0, amount_min_fees,
                                        emer_pubkeys)
    # Simulate that each stakeholder sign the transaction separately
    sigs = [sign_emergency_vault_tx(emer_tx, stk_pubkeys, amount, [k])[0]
            for k in stk_privkeys]
    emer_tx = form_emergency_vault_tx(emer_tx, stk_pubkeys, sigs)
    bitcoind.send_tx(b2x(emer_tx.serialize()))


def send_unvault_tx(bitcoind, stk_privkeys, stk_pubkeys, serv_pubkey,
                    amount_vault, amount_unvault):
    vault_txid = lx(send_vault_tx(bitcoind, stk_pubkeys, amount_vault))
    unvtx = create_unvault_tx(vault_txid, 0, stk_pubkeys, serv_pubkey,
                              amount_unvault)
    sigs = sign_unvault_tx(unvtx, stk_pubkeys, amount_vault, stk_privkeys)
    unvtx = form_unvault_tx(unvtx, stk_pubkeys, sigs)
    bitcoind.send_tx(b2x(unvtx.serialize()))
    return unvtx.GetTxid()


def test_cancel_unvault_tx(bitcoind):
    """This tests that cancel_unvault_tx() produces a valid transaction."""
    # The stakeholders, the first two are the traders.
    stk_privkeys = [os.urandom(32) for i in range(4)]
    stk_pubkeys = [CKey(k).pub for k in stk_privkeys]
    # The co-signing server, required by the spend tx
    serv_privkey = CKey(os.urandom(32))
    serv_pubkey = serv_privkey.pub
    # Create the vault and unvault transactions
    amount_vault = 50 * COIN - 500
    amount_unvault = amount_vault - 500
    txid = send_unvault_tx(bitcoind, stk_privkeys, stk_pubkeys, serv_pubkey,
                           amount_vault, amount_unvault)
    amount_cancel = amount_unvault - 500
    # We re-spend to the same vault
    CTx = create_cancel_tx(txid, 0, stk_pubkeys, amount_cancel)
    sigs = [sign_cancel_tx(CTx, [p], stk_pubkeys, serv_pubkey,
                           amount_unvault)[0]
            for p in stk_privkeys]
    CTx = form_cancel_tx(CTx, sigs, stk_pubkeys, serv_pubkey)
    bitcoind.send_tx(b2x(CTx.serialize()))


def test_emergency_unvault_tx(bitcoind):
    """This tests the emergency_unvault_tx() function."""
    # The stakeholders, the first two are the traders.
    stk_privkeys = [os.urandom(32) for i in range(4)]
    stk_pubkeys = [CKey(k).pub for k in stk_privkeys]
    # The stakeholders emergency keys
    emer_privkeys = [os.urandom(32) for i in range(4)]
    emer_pubkeys = [CKey(k).pub for k in emer_privkeys]
    # The co-signing server, required by the spend tx
    serv_privkey = CKey(os.urandom(32))
    serv_pubkey = serv_privkey.pub
    # Create the vault and unvault transactions
    amount_vault = 50 * COIN - 500
    amount_unvault = amount_vault - 500
    txid = send_unvault_tx(bitcoind, stk_privkeys, stk_pubkeys, serv_pubkey,
                           amount_vault, amount_unvault)
    amount_emer = amount_unvault - 500
    # Actually vout MUST be 0.
    CTx = create_emer_unvault_tx(txid, 0, emer_pubkeys, amount_emer)
    sigs = [sign_emer_unvault_tx(CTx, [p], stk_pubkeys, serv_pubkey,
                                 amount_unvault)[0]
            for p in stk_privkeys]
    CTx = form_emer_unvault_tx(CTx, sigs, stk_pubkeys, serv_pubkey)
    bitcoind.send_tx(b2x(CTx.serialize()))


def test_spend_unvault_tx_two_traders(bitcoind):
    """
    This tests the unvault_tx spending with the signature of the two traders.
    """
    # The stakeholders, the first two are the traders.
    stk_privkeys = [os.urandom(32) for i in range(4)]
    stk_pubkeys = [CKey(k).pub for k in stk_privkeys]
    # The co-signing server, required by the spend tx
    serv_privkey = os.urandom(32)
    serv_pubkey = CKey(serv_privkey).pub
    # Create the vault and unvault transactions
    amount_vault = 50 * COIN - 500
    amount_unvault = amount_vault - 500
    txid = send_unvault_tx(bitcoind, stk_privkeys, stk_pubkeys, serv_pubkey,
                           amount_vault, amount_unvault)
    amount_spend = amount_unvault - 500
    # The address to spend to
    addr = bitcoind.getnewaddress()
    CTx = create_spend_tx(txid, 0, {addr: amount_spend})
    # The first two stakeholders are the traders
    sigs = sign_spend_tx(CTx, stk_privkeys[:2], stk_pubkeys, serv_pubkey,
                         amount_unvault)
    # We need the cosigning server sig, too !
    sig_serv = sign_spend_tx(CTx, [serv_privkey], stk_pubkeys, serv_pubkey,
                             amount_unvault)
    # Ok we have all the sigs we need, let's spend it...
    CTx = form_spend_tx(CTx, stk_pubkeys, serv_pubkey,
                        [*sigs, bytes(0), *sig_serv])
    # ... After the relative locktime !
    for i in range(5):
        with pytest.raises(VerifyRejectedError, match="non-BIP68-final"):
            bitcoind.send_tx(b2x(CTx.serialize()))
        bitcoind.generate_block(1)
    bitcoind.send_tx(b2x(CTx.serialize()))
    assert bitcoind.has_utxo(addr)


def test_spend_unvault_tx_trader_second_trader(bitcoind):
    """
    This tests the unvault transaction spending with the signatures of
    the second trader and the stakeholder.
    """
    # The stakeholders, the first two are the traders.
    stk_privkeys = [os.urandom(32) for i in range(4)]
    stk_pubkeys = [CKey(k).pub for k in stk_privkeys]
    # The co-signing server, required by the spend tx
    serv_privkey = os.urandom(32)
    serv_pubkey = CKey(serv_privkey).pub
    # Create the vault and unvault transactions
    amount_vault = 50 * COIN - 500
    amount_unvault = amount_vault - 500
    txid = send_unvault_tx(bitcoind, stk_privkeys, stk_pubkeys, serv_pubkey,
                           amount_vault, amount_unvault)
    amount_spend = amount_unvault - 500
    # The address to spend to
    addr = bitcoind.getnewaddress()
    CTx = create_spend_tx(txid, 0, {addr: amount_spend})
    # The first two stakeholders are the traders
    sigs = sign_spend_tx(CTx, stk_privkeys[1:3], stk_pubkeys,
                         serv_pubkey, amount_unvault)
    # We need the cosigning server sig, too !
    sig_serv = sign_spend_tx(CTx, [serv_privkey], stk_pubkeys,
                             serv_pubkey, amount_unvault)
    # Ok we have all the sigs we need, let's spend it...
    CTx = form_spend_tx(CTx, stk_pubkeys, serv_pubkey,
                        [bytes(0), *sigs, *sig_serv])
    # ... After the relative locktime !
    for i in range(5):
        with pytest.raises(VerifyRejectedError, match="non-BIP68-final"):
            bitcoind.send_tx(b2x(CTx.serialize()))
        bitcoind.generate_block(1)
    bitcoind.send_tx(b2x(CTx.serialize()))
    assert bitcoind.has_utxo(addr)


def test_spend_unvault_tx_trader_A(bitcoind):
    """
    This tests the unvault transaction spending with the signature of the first
    trader and the stakeholder.
    """
    # The stakeholders, the first two are the traders.
    stk_privkeys = [os.urandom(32) for i in range(4)]
    stk_pubkeys = [CKey(k).pub for k in stk_privkeys]
    # The co-signing server, required by the spend tx
    serv_privkey = os.urandom(32)
    serv_pubkey = CKey(serv_privkey).pub
    # Create the vault and unvault transactions
    amount_vault = 50 * COIN - 500
    amount_unvault = amount_vault - 500
    txid = send_unvault_tx(bitcoind, stk_privkeys, stk_pubkeys, serv_pubkey,
                           amount_vault, amount_unvault)
    amount_spend = amount_unvault - 500

    # The address to spend to
    addr = bitcoind.getnewaddress()
    CTx = create_spend_tx(txid, 0, {addr: amount_spend})
    # The first two stakeholders are the traders
    sigs = sign_spend_tx(CTx, [stk_privkeys[0], stk_privkeys[2]],
                         stk_pubkeys, serv_pubkey, amount_unvault)
    # We need the cosigning server sig, too !
    sig_serv = sign_spend_tx(CTx, [serv_privkey], stk_pubkeys, serv_pubkey,
                             amount_unvault)
    # Ok we have all the sigs we need, let's spend it...
    CTx = form_spend_tx(CTx, stk_pubkeys, serv_pubkey,
                        [sigs[0], bytes(0), sigs[1], *sig_serv])
    # ... After the relative locktime !
    for i in range(5):
        with pytest.raises(VerifyRejectedError, match="non-BIP68-final"):
            bitcoind.send_tx(b2x(CTx.serialize()))
        bitcoind.generate_block(1)
    bitcoind.send_tx(b2x(CTx.serialize()))
    assert bitcoind.has_utxo(addr)
