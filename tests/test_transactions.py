import bitcoin
import hashlib
import os
import pytest

from bitcoin.core import (
    CTxIn, CTxOut, COutPoint, CTxInWitness, CMutableTransaction, CTxWitness,
    b2x, lx, COIN, CScript, Hash160, b2lx,
)
from bitcoin.rpc import VerifyRejectedError
from bitcoin.core.script import (
    CScriptWitness, SIGHASH_ALL, SIGHASH_SINGLE, SIGHASH_ANYONECANPAY,
    SIGVERSION_WITNESS_V0, SignatureHash, OP_0,
)
from bitcoin.wallet import CBitcoinAddress, CKey
from decimal import Decimal
from fixtures import *  # noqa: F401,F403
from revault.transactions import (
    vault_txout, vault_script, unvault_txout, unvault_script, emergency_txout,
    emergency_script, create_unvault_tx, sign_unvault_tx, form_unvault_tx,
    create_emergency_vault_tx, sign_emergency_vault_tx,
    form_emergency_vault_tx, create_cancel_tx, sign_cancel_tx, form_cancel_tx,
    create_emer_unvault_tx, sign_emer_unvault_tx, form_emer_unvault_tx,
    create_spend_tx, sign_spend_tx, form_spend_tx,
)


bitcoin.SelectParams("regtest")


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


def test_big_vault_txout(bitcoind):
    from bitcoin.core.script import (
        OP_CHECKSIG, OP_CHECKSIGVERIFY
    )

    privkeys = [CKey(os.urandom(32)) for _ in range(100)]
    pubkeys = [k.pub for k in privkeys]
    amount = 50 * COIN - 500

    script = []
    for pubkey in pubkeys[:-1]:
        script += [pubkey, OP_CHECKSIGVERIFY]
    script += [pubkeys[-1], OP_CHECKSIG]
    vault_script = CScript(script)
    p2wsh = CScript([OP_0, hashlib.sha256(vault_script).digest()])
    vault_txo = CTxOut(amount, p2wsh)
    addr = str(CBitcoinAddress.from_scriptPubKey(vault_txo.scriptPubKey))
    # This makes a transaction with only one vout
    txid = bitcoind.pay_to(addr, amount / COIN)
    print(bitcoind.rpc.getrawtransaction(txid))

    new_amount = amount - 5000
    addr = bitcoind.getnewaddress()
    dest_txo = CTxOut(new_amount, CBitcoinAddress(addr).to_scriptPubKey())
    vault_txin = CTxIn(COutPoint(lx(txid), 0))
    tx = CMutableTransaction([vault_txin], [dest_txo])
    tx_hash = SignatureHash(vault_script, tx, 0,
                            SIGHASH_ALL, amount=amount,
                            sigversion=SIGVERSION_WITNESS_V0)
    sigs = [k.sign(tx_hash) + bytes([SIGHASH_ALL]) for k in privkeys]
    witness_script = [*sigs[::-1], vault_script]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])

    print(tx.serialize().hex())
    bitcoind.send_tx(tx.serialize().hex())
    assert bitcoind.has_utxo(addr)


def test_big_unvault_txout(bitcoind):
    from bitcoin.core.script import (
        OP_CHECKSIG, OP_IF, OP_ELSE, OP_ENDIF,
        OP_CHECKSEQUENCEVERIFY, OP_CHECKSIGVERIFY, OP_DROP
    )
    # This dirty test doesnt handle n_participants == n_traders
    n_participants = 68
    n_traders = 34

    part_privkeys = [CKey(os.urandom(32)) for _ in range(n_participants)]
    part_pubkeys = [k.pub for k in part_privkeys]
    trad_privkeys = [part_privkeys[i] for i in range(n_traders)]
    trad_pubkeys = [k.pub for k in trad_privkeys]
    cosig_privkeys = [CKey(os.urandom(32)) for _ in range(n_participants -
                                                          n_traders)]
    cosig_pubkeys = [k.pub for k in cosig_privkeys]

    amount = 50 * COIN - 500

    script = []
    # All branchs needs the traders sigs
    for pubkey in trad_pubkeys:
        script += [pubkey, OP_CHECKSIGVERIFY]
    # If it wants to spend the all-sign path
    script += [OP_IF]
    for pubkey in part_pubkeys[len(trad_pubkeys):-1]:
        script += [pubkey, OP_CHECKSIGVERIFY]
    # The strict "1 must remain on the stack" rule
    script += [part_pubkeys[-1], OP_CHECKSIG]
    # Otherwise, we lock for 6 blocks and need the cosigning servers sigs
    script += [OP_ELSE, 6, OP_CHECKSEQUENCEVERIFY, OP_DROP]
    for pubkey in cosig_pubkeys[:-1]:
        script += [pubkey, OP_CHECKSIGVERIFY]
    # The strict "1 must remain on the stack" rule
    script += [cosig_pubkeys[-1], OP_CHECKSIG, OP_ENDIF]

    unvault_script = CScript(script)
    p2wsh = CScript([OP_0, hashlib.sha256(unvault_script).digest()])
    unvault_txo = CTxOut(amount, p2wsh)
    addr = str(CBitcoinAddress.from_scriptPubKey(unvault_txo.scriptPubKey))

    # This makes a transaction with only one vout
    txid = bitcoind.pay_to(addr, amount / COIN)
    print(bitcoind.rpc.getrawtransaction(txid))  # For btcdeb --txin

    # Try the everyone-is-signing path
    new_amount = amount - 2500
    addr = bitcoind.getnewaddress()
    dest_txo = CTxOut(new_amount, CBitcoinAddress(addr).to_scriptPubKey())
    unvault_txin = CTxIn(COutPoint(lx(txid), 0))
    tx = CMutableTransaction([unvault_txin], [dest_txo], nVersion=2)
    tx_hash = SignatureHash(unvault_script, tx, 0,
                            SIGHASH_ALL, amount=amount,
                            sigversion=SIGVERSION_WITNESS_V0)
    trad_sigs = [k.sign(tx_hash) + bytes([SIGHASH_ALL]) for k in
                 part_privkeys[:len(trad_privkeys)]]
    other_sigs = [k.sign(tx_hash) + bytes([SIGHASH_ALL]) for k in
                  part_privkeys[len(trad_privkeys):]]
    witness_script = [*other_sigs[::-1], b'\x01', *trad_sigs[::-1],
                      unvault_script]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])

    print(tx.serialize().hex())
    bitcoind.send_tx(tx.serialize().hex())
    assert bitcoind.has_utxo(addr)

    # Now the timelocked path CODE DUPLICATION GO BRRRRRR

    unvault_script = CScript(script)
    p2wsh = CScript([OP_0, hashlib.sha256(unvault_script).digest()])
    unvault_txo = CTxOut(amount, p2wsh)
    addr = str(CBitcoinAddress.from_scriptPubKey(unvault_txo.scriptPubKey))
    # This makes a transaction with only one vout
    txid = bitcoind.pay_to(addr, amount / COIN)
    print(bitcoind.rpc.getrawtransaction(txid))  # For btcdeb --txin

    new_amount = amount - 2500
    addr = bitcoind.getnewaddress()
    dest_txo = CTxOut(new_amount, CBitcoinAddress(addr).to_scriptPubKey())
    unvault_txin = CTxIn(COutPoint(lx(txid), 0), nSequence=6)
    tx = CMutableTransaction([unvault_txin], [dest_txo], nVersion=2)
    tx_hash = SignatureHash(unvault_script, tx, 0,
                            SIGHASH_ALL, amount=amount,
                            sigversion=SIGVERSION_WITNESS_V0)
    trad_sigs = [k.sign(tx_hash) + bytes([SIGHASH_ALL]) for k in trad_privkeys]
    cosigs = [k.sign(tx_hash) + bytes([SIGHASH_ALL]) for k in cosig_privkeys]
    witness_script = [*cosigs[::-1], bytes(0), *trad_sigs[::-1],
                      unvault_script]
    witness = CTxInWitness(CScriptWitness(witness_script))
    tx.wit = CTxWitness([witness])

    print(tx.serialize().hex())
    # Relative locktime !
    for i in range(5):
        with pytest.raises(VerifyRejectedError, match="non-BIP68-final"):
            bitcoind.send_tx(b2x(tx.serialize()))
        bitcoind.generate_block(1)
    # It's been 6 blocks now
    bitcoind.send_tx(b2x(tx.serialize()))
    assert bitcoind.has_utxo(addr)


def get_tx_weight(bitcoind, tx):
    return bitcoind.rpc.decoderawtransaction(tx.serialize().hex())["weight"]


def test_unvault_size(bitcoind):
    """A hack to print the size of the unvault according to the number of
    participants."""
    from bitcoin.core.script import (
        OP_CHECKSIG, OP_IF, OP_ELSE, OP_ENDIF,
        OP_CHECKSEQUENCEVERIFY, OP_CHECKSIGVERIFY, OP_DROP
    )
    for n_participants in range(4, 68):
        n_traders = n_participants // 2
        print("Number of participants: {}, number in the subset: {}"
              .format(n_participants, n_traders))

        part_privkeys = [CKey(os.urandom(32)) for _ in range(n_participants)]
        part_pubkeys = [k.pub for k in part_privkeys]
        trad_privkeys = [part_privkeys[i] for i in range(n_traders)]
        trad_pubkeys = [k.pub for k in trad_privkeys]
        cosig_privkeys = [CKey(os.urandom(32)) for _ in range(n_participants -
                                                              n_traders)]
        cosig_pubkeys = [k.pub for k in cosig_privkeys]

        vault_amount = 50 * COIN - 500

        # First pay to a vault
        vscript = []
        for pubkey in part_pubkeys[:-1]:
            vscript += [pubkey, OP_CHECKSIGVERIFY]
        vscript += [part_pubkeys[-1], OP_CHECKSIG]
        vault_script = CScript(vscript)
        p2wsh = CScript([OP_0, hashlib.sha256(vault_script).digest()])
        vault_txo = CTxOut(vault_amount, p2wsh)
        vault_addr = str(CBitcoinAddress
                         .from_scriptPubKey(vault_txo.scriptPubKey))
        # This makes a transaction with only one vout
        txid = bitcoind.pay_to(vault_addr, vault_amount / COIN)

        # Now make an unvault tx which spends it
        uvscript = []
        # All branchs needs the traders sigs
        for pubkey in trad_pubkeys:
            uvscript += [pubkey, OP_CHECKSIGVERIFY]
        # If it wants to spend the all-sign path
        uvscript += [OP_IF]
        for pubkey in part_pubkeys[len(trad_pubkeys):-1]:
            uvscript += [pubkey, OP_CHECKSIGVERIFY]
        # The strict "1 must remain on the stack" rule
        uvscript += [part_pubkeys[-1], OP_CHECKSIG]
        # Otherwise, we lock for 6 blocks and need the cosigning servers sigs
        uvscript += [OP_ELSE, 6, OP_CHECKSEQUENCEVERIFY, OP_DROP]
        for pubkey in cosig_pubkeys[:-1]:
            uvscript += [pubkey, OP_CHECKSIGVERIFY]
        # The strict "1 must remain on the stack" rule
        uvscript += [cosig_pubkeys[-1], OP_CHECKSIG, OP_ENDIF]

        unvault_script = CScript(uvscript)
        p2wsh = CScript([OP_0, hashlib.sha256(unvault_script).digest()])
        unvault_txo = CTxOut(0, p2wsh)
        unvault_addr = str(CBitcoinAddress
                           .from_scriptPubKey(unvault_txo.scriptPubKey))

        unvault_amount = vault_amount - 5000
        dest_txo = CTxOut(unvault_amount,
                          CBitcoinAddress(unvault_addr).to_scriptPubKey())
        vault_txin = CTxIn(COutPoint(lx(txid), 0))
        tx = CMutableTransaction([vault_txin], [dest_txo])
        tx_hash = SignatureHash(vault_script, tx, 0,
                                SIGHASH_ALL, amount=vault_amount,
                                sigversion=SIGVERSION_WITNESS_V0)
        sigs = [k.sign(tx_hash) + bytes([SIGHASH_ALL])
                for k in part_privkeys]
        witness_script = [*sigs[::-1], vault_script]
        witness = CTxInWitness(CScriptWitness(witness_script))
        tx.wit = CTxWitness([witness])

        print("Size of the unvault tx: {} WU"
              .format(get_tx_weight(bitcoind, tx)))
        bitcoind.send_tx(tx.serialize().hex())

        # Try the everyone-is-signing path
        new_amount = unvault_amount - 2500
        addr = bitcoind.getnewaddress()
        dest_txo = CTxOut(new_amount, CBitcoinAddress(addr).to_scriptPubKey())
        unvault_txin = CTxIn(COutPoint(tx.GetTxid(), 0))
        tx = CMutableTransaction([unvault_txin], [dest_txo], nVersion=2)
        tx_hash = SignatureHash(unvault_script, tx, 0,
                                SIGHASH_ALL, amount=unvault_amount,
                                sigversion=SIGVERSION_WITNESS_V0)
        trad_sigs = [k.sign(tx_hash) + bytes([SIGHASH_ALL]) for k in
                     part_privkeys[:len(trad_privkeys)]]
        other_sigs = [k.sign(tx_hash) + bytes([SIGHASH_ALL]) for k in
                      part_privkeys[len(trad_privkeys):]]
        witness_script = [*other_sigs[::-1], b'\x01', *trad_sigs[::-1],
                          unvault_script]
        witness = CTxInWitness(CScriptWitness(witness_script))
        tx.wit = CTxWitness([witness])

        print("Size of the revaulting txs: {} WU"
              .format(get_tx_weight(bitcoind, tx)))
        bitcoind.send_tx(tx.serialize().hex())
        assert bitcoind.has_utxo(addr)

        # Now the timelocked path CODE DUPLICATION GO BRRRRRR

        # First pay to a vault
        vscript = []
        for pubkey in part_pubkeys[:-1]:
            vscript += [pubkey, OP_CHECKSIGVERIFY]
        vscript += [part_pubkeys[-1], OP_CHECKSIG]
        vault_script = CScript(vscript)
        p2wsh = CScript([OP_0, hashlib.sha256(vault_script).digest()])
        vault_txo = CTxOut(vault_amount, p2wsh)
        vault_addr = str(CBitcoinAddress
                         .from_scriptPubKey(vault_txo.scriptPubKey))
        # This makes a transaction with only one vout
        txid = bitcoind.pay_to(vault_addr, vault_amount / COIN)

        unvault_script = CScript(uvscript)
        p2wsh = CScript([OP_0, hashlib.sha256(unvault_script).digest()])
        unvault_txo = CTxOut(0, p2wsh)
        unvault_addr = str(CBitcoinAddress
                           .from_scriptPubKey(unvault_txo.scriptPubKey))

        unvault_amount = vault_amount - 5000
        dest_txo = CTxOut(unvault_amount,
                          CBitcoinAddress(unvault_addr).to_scriptPubKey())
        vault_txin = CTxIn(COutPoint(lx(txid), 0))
        tx = CMutableTransaction([vault_txin], [dest_txo])
        tx_hash = SignatureHash(vault_script, tx, 0,
                                SIGHASH_ALL, amount=vault_amount,
                                sigversion=SIGVERSION_WITNESS_V0)
        sigs = [k.sign(tx_hash) + bytes([SIGHASH_ALL])
                for k in part_privkeys]
        witness_script = [*sigs[::-1], vault_script]
        witness = CTxInWitness(CScriptWitness(witness_script))
        tx.wit = CTxWitness([witness])
        bitcoind.send_tx(tx.serialize().hex())

        new_amount = unvault_amount - 2500
        addr = bitcoind.getnewaddress()
        dest_txo = CTxOut(new_amount, CBitcoinAddress(addr).to_scriptPubKey())
        unvault_txin = CTxIn(COutPoint(tx.GetTxid(), 0), nSequence=6)
        tx = CMutableTransaction([unvault_txin], [dest_txo], nVersion=2)
        tx_hash = SignatureHash(unvault_script, tx, 0,
                                SIGHASH_ALL, amount=unvault_amount,
                                sigversion=SIGVERSION_WITNESS_V0)
        trad_sigs = [k.sign(tx_hash) + bytes([SIGHASH_ALL])
                     for k in trad_privkeys]
        cosigs = [k.sign(tx_hash) + bytes([SIGHASH_ALL])
                  for k in cosig_privkeys]
        witness_script = [*cosigs[::-1], bytes(0), *trad_sigs[::-1],
                          unvault_script]
        witness = CTxInWitness(CScriptWitness(witness_script))
        tx.wit = CTxWitness([witness])

        print("Size of the spend tx: {} WU"
              .format(get_tx_weight(bitcoind, tx)))
        # Relative locktime !
        bitcoind.generate_block(5)
        # It's been 6 blocks now
        bitcoind.send_tx(b2x(tx.serialize()))
        assert bitcoind.has_utxo(addr)
        print("============================================\n\n")

    assert False  # Show the prints


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
    sigs += [bytes(0)]
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
    sigs = [sign_unvault_tx(unvtx, k, stk_pubkeys, amount)
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
    sigs = [sign_emergency_vault_tx(emer_tx, k, stk_pubkeys, amount)
            for k in stk_privkeys]
    emer_tx = form_emergency_vault_tx(emer_tx, stk_pubkeys, sigs)
    bitcoind.send_tx(b2x(emer_tx.serialize()))


def send_unvault_tx(bitcoind, stk_privkeys, stk_pubkeys, serv_pubkey,
                    amount_vault, amount_unvault):
    vault_txid = lx(send_vault_tx(bitcoind, stk_pubkeys, amount_vault))
    unvtx = create_unvault_tx(vault_txid, 0, stk_pubkeys, serv_pubkey,
                              amount_unvault)
    assert len(unvtx.vout) == 1 and len(unvtx.vin) == 1
    sigs = [sign_unvault_tx(unvtx, key, stk_pubkeys, amount_vault)
            for key in stk_privkeys]
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
    sigs = [sign_cancel_tx(CTx, p, stk_pubkeys, serv_pubkey, amount_unvault)
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
    sigs = [sign_emer_unvault_tx(CTx, p, stk_pubkeys, serv_pubkey,
                                 amount_unvault)
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
    sigs = [sign_spend_tx(CTx, key, stk_pubkeys, serv_pubkey, amount_unvault)
            for key in stk_privkeys[:2]]
    # We need the cosigning server sig, too !
    sig_serv = sign_spend_tx(CTx, serv_privkey, stk_pubkeys, serv_pubkey,
                             amount_unvault)
    # Ok we have all the sigs we need, let's spend it...
    CTx = form_spend_tx(CTx, stk_pubkeys, serv_pubkey,
                        [*sigs, bytes(0), sig_serv])
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
    sigs = [sign_spend_tx(CTx, key, stk_pubkeys, serv_pubkey, amount_unvault)
            for key in stk_privkeys[1:3]]
    # We need the cosigning server sig, too !
    sig_serv = sign_spend_tx(CTx, serv_privkey, stk_pubkeys, serv_pubkey,
                             amount_unvault)
    # Ok we have all the sigs we need, let's spend it...
    CTx = form_spend_tx(CTx, stk_pubkeys, serv_pubkey,
                        [bytes(0), *sigs, sig_serv])
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
    sigs = [sign_spend_tx(CTx, key, stk_pubkeys, serv_pubkey, amount_unvault)
            for key in [stk_privkeys[0], stk_privkeys[2]]]
    # We need the cosigning server sig, too !
    sig_serv = sign_spend_tx(CTx, serv_privkey, stk_pubkeys, serv_pubkey,
                             amount_unvault)
    # Ok we have all the sigs we need, let's spend it...
    CTx = form_spend_tx(CTx, stk_pubkeys, serv_pubkey,
                        [sigs[0], bytes(0), sigs[1], sig_serv])
    # ... After the relative locktime !
    for i in range(5):
        with pytest.raises(VerifyRejectedError, match="non-BIP68-final"):
            bitcoind.send_tx(b2x(CTx.serialize()))
        bitcoind.generate_block(1)
    bitcoind.send_tx(b2x(CTx.serialize()))
    assert bitcoind.has_utxo(addr)


def add_input_output(bitcoind, tx):
    """Add an input and an output to a CMutableTransaction, SIGHASH_ALL."""
    # First we get some coins
    privkey = CKey(os.urandom(32))
    scriptPubKey = CScript([OP_0, Hash160(privkey.pub)])
    address = CBitcoinAddress.from_scriptPubKey(scriptPubKey)
    amount = Decimal("50") * Decimal(COIN) - Decimal("500")
    # This creates a one-output transaction
    txid = bitcoind.pay_to(str(address), amount / Decimal(COIN))
    # We bump the fees by 5000
    tx.vout.append(CTxOut(amount - Decimal("5000"), scriptPubKey))
    tx.vin.append(CTxIn(COutPoint(lx(txid), 0)))
    # Sign the new output with ALL
    tx_hash = SignatureHash(address.to_redeemScript(), tx, 1, SIGHASH_ALL,
                            int(amount), SIGVERSION_WITNESS_V0)
    sig = privkey.sign(tx_hash) + bytes([SIGHASH_ALL])
    tx.wit.vtxinwit.append(CTxInWitness(CScriptWitness([sig, privkey.pub])))


def tx_fees(bitcoind, tx):
    """Computes the transaction fees of a CTransaction"""
    value_in = sum(
        bitcoind.rpc.getrawtransaction(
            b2lx(txin.prevout.hash), True)["vout"][txin.prevout.n]["value"]
        for txin in tx.vin
    )
    value_out = sum(o.nValue for o in tx.vout)

    # bitcoind API in btc...
    return value_in * Decimal(COIN) - value_out


def test_increase_revault_tx_feerate(bitcoind):
    """This tests that any of the stakeholders can increase the feerate of any
    of the revaulting transactions in a timely manner. Will justice rule?"""
    # The stakeholders, the first two are the traders.
    stk_privkeys = [os.urandom(32) for i in range(4)]
    stk_pubkeys = [CKey(k).pub for k in stk_privkeys]
    # Same, but for the EDV
    emer_privkeys = [os.urandom(32) for i in range(4)]
    emer_pubkeys = [CKey(k).pub for k in emer_privkeys]
    # The co-signing server, required by the spend tx
    serv_privkey = os.urandom(32)
    serv_pubkey = CKey(serv_privkey).pub

    # Test the vault emergency
    amount_vault = 50 * COIN - 500
    txid = send_vault_tx(bitcoind, stk_pubkeys, amount_vault)
    amount_emer = amount_vault - 500
    CTx = create_emergency_vault_tx(lx(txid), 0, amount_emer, emer_pubkeys)
    sigs = [sign_emergency_vault_tx(CTx, p, stk_pubkeys, amount_vault)
            for p in stk_privkeys]
    # Sanity checks don't hurt
    assert all(sig[-1] == SIGHASH_SINGLE | SIGHASH_ANYONECANPAY
               for sig in sigs)
    CMTx = CMutableTransaction.from_tx(
        form_emergency_vault_tx(CTx, stk_pubkeys, sigs)
    )
    fees_before = tx_fees(bitcoind, CMTx)
    add_input_output(bitcoind, CMTx)
    fees_after = tx_fees(bitcoind, CMTx)
    assert fees_after > fees_before
    bitcoind.send_tx(CMTx.serialize().hex())

    # Test the emer unvault
    amount_vault = 50 * COIN - 500
    amount_unvault = amount_vault - 500
    txid = send_unvault_tx(bitcoind, stk_privkeys, stk_pubkeys, serv_pubkey,
                           amount_vault, amount_unvault)
    amount_emer = amount_unvault - 500
    CTx = create_emer_unvault_tx(txid, 0, emer_pubkeys, amount_emer)
    sigs = [sign_emer_unvault_tx(CTx, p, stk_pubkeys, serv_pubkey,
                                 amount_unvault)
            for p in stk_privkeys]
    # Sanity checks don't hurt
    assert all(sig[-1] == SIGHASH_SINGLE | SIGHASH_ANYONECANPAY
               for sig in sigs)
    CMTx = CMutableTransaction.from_tx(
        form_emer_unvault_tx(CTx, sigs, stk_pubkeys, serv_pubkey)
    )
    fees_before = tx_fees(bitcoind, CMTx)
    add_input_output(bitcoind, CMTx)
    fees_after = tx_fees(bitcoind, CMTx)
    assert fees_after > fees_before
    bitcoind.send_tx(CMTx.serialize().hex())

    # Test the cancel unvault
    amount_vault = 50 * COIN - 500
    amount_unvault = amount_vault - 500
    txid = send_unvault_tx(bitcoind, stk_privkeys, stk_pubkeys, serv_pubkey,
                           amount_vault, amount_unvault)
    amount_cancel = amount_unvault - 500
    CTx = create_cancel_tx(txid, 0, emer_pubkeys, amount_cancel)
    sigs = [sign_cancel_tx(CTx, p, stk_pubkeys, serv_pubkey,
                           amount_unvault)
            for p in stk_privkeys]
    # Sanity checks don't hurt
    assert all(sig[-1] == SIGHASH_SINGLE | SIGHASH_ANYONECANPAY
               for sig in sigs)
    CMTx = CMutableTransaction.from_tx(
        form_cancel_tx(CTx, sigs, stk_pubkeys, serv_pubkey)
    )
    fees_before = tx_fees(bitcoind, CMTx)
    add_input_output(bitcoind, CMTx)
    fees_after = tx_fees(bitcoind, CMTx)
    assert fees_after > fees_before
    bitcoind.send_tx(CMTx.serialize().hex())
