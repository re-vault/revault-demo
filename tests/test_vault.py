import bitcoin
import random

from bip32 import BIP32
from bitcoin.core import b2x, COIN
from bitcoin.wallet import CKey
from fixtures import *  # noqa: F401,F403
from utils import wait_for


bitcoin.SelectParams("regtest")


def test_vault_address(vault_factory):
    vaults = vault_factory.get_vaults()
    # FIXME: separate the Bitcoin backends !!
    bitcoind = vaults[0].bitcoind
    for vault in vaults:
        # It's burdensome to our xpub to be None in the list, but it allows us
        # to know which of the stakeholders we are, so..
        all_xpubs = [keychain.get_master_xpub() if keychain
                     else vault.our_bip32.get_master_xpub()
                     for keychain in vault.keychains]
        # bitcoind should always return the same address as us
        for i in range(3):
            vault_first_address = vault.getnewaddress()
            bitcoind_first_address = bitcoind.addmultisigaddress(4, [
                b2x(BIP32.from_xpub(xpub).get_pubkey_from_path([i]))
                for xpub in all_xpubs
            ])["address"]
            assert vault_first_address == bitcoind_first_address


def test_sigserver(bitcoind, sigserv):
    """We just test that it stores sigs correctly."""
    sig = "a01f"
    txid = "0101"
    stk_id = 1
    # POST a dummy sig
    r = sigserv.post("sig/{}/{}".format(txid, stk_id),
                     data={"sig": sig})
    assert r.status_code == 201
    assert r.json == {"sig": sig}
    # GET it
    r = sigserv.get("sig/{}/{}".format(txid, stk_id))
    assert r.status_code == 200
    assert r.json == {"sig": sig}


def test_sigserver_feerate(vault_factory):
    """We just test that it gives us a (valid) feerate."""
    vault = vault_factory.get_vaults()[0]
    # GET emergency feerate
    feerate = vault.sigserver.get_feerate("emergency", txid="high_entropy")
    # sats/vbyte, if it's less there's something going on !
    assert feerate >= 1


def test_signatures_posting(vault_factory):
    """Test that we can send signatures to the sig server."""
    vault = vault_factory.get_vaults()[0]
    vault.sigserver.send_signature("00af", "aa56")


def test_funds_polling(vault_factory):
    """Test that we are aware of the funds we receive."""
    vault = vault_factory.get_vaults()[0]
    # FIXME: separate the Bitcoin backends !!
    bitcoind = vault.bitcoind
    assert len(vault.vaults) == 0
    # Send new funds to it
    for i in range(3):
        bitcoind.pay_to(vault.getnewaddress(), 10)
    wait_for(lambda: len(vault.vaults) == 3)
    # Retry with a gap
    for _ in range(20):
        vault.getnewaddress()
    for i in range(2):
        bitcoind.pay_to(vault.getnewaddress(), 10)
    wait_for(lambda: len(vault.vaults) == 5)


def test_emergency_sig_sharing(vault_factory):
    """Test that we share the emergency transaction signature."""
    vault = vault_factory.get_vaults()[0]
    # FIXME: separate the Bitcoin backends !!
    bitcoind = vault.bitcoind
    assert len(vault.vaults) == 0
    # Send new funds to it
    bitcoind.pay_to(vault.getnewaddress(), 10)
    wait_for(lambda: len(vault.vaults) == 1)
    wait_for(lambda:
             vault.vaults[0]["emergency_sigs"][vault.keychains.index(None)] is
             not None)


def test_emergency_tx_sync(vault_factory):
    """Test that we correctly share and gather emergency transactions
    signatures."""
    vaults = vault_factory.get_vaults()
    # FIXME: separate the Bitcoin backends !!
    bitcoind = vaults[0].bitcoind
    # Sending funds to any vault address will be remarked by anyone
    for vault in vaults:
        bitcoind.pay_to(vault.getnewaddress(), 10)
    wait_for(lambda: all(len(v.vaults) == len(vaults) for v in vaults))
    # FIXME: too much "vault" vars
    for wallet in vaults:
        wait_for(lambda: all(vault["emergency_signed"]
                             for vault in wallet.vaults))
    # All nodes should have the same emergency transactions
    for i in range(len(vaults) - 1):
        first_emer_txs = [v["emergency_tx"] for v in vaults[i].vaults]
        second_emer_txs = [v["emergency_tx"] for v in vaults[i + 1].vaults]
        for tx in first_emer_txs:
            assert tx == second_emer_txs[first_emer_txs.index(tx)]


def test_emergency_broadcast(vault_factory):
    """Test that all the emergency transactions we create are valid and can be
    broadcast."""
    vaults = vault_factory.get_vaults()
    # FIXME: separate the Bitcoin backends !!
    bitcoind = vaults[0].bitcoind
    # Sending funds to any vault address will be remarked by anyone
    for vault in vaults:
        for _ in range(2):
            bitcoind.pay_to(vault.getnewaddress(), 10)
    wait_for(lambda: all(len(v.vaults) == 2 * len(vaults) for v in vaults))
    wait_for(lambda: all(v["emergency_signed"] for v in vault.vaults))
    vault = random.choice(vaults)
    for tx in [v["emergency_tx"] for v in vault.vaults]:
        bitcoind.broadcast_and_mine(b2x(tx.serialize()))
    wait_for(lambda: len(vault.vaults) == 0)


def test_vault_address_reuse(vault_factory):
    """Test that we are still safe if coins are sent to an already used vault.
    """
    vaults = vault_factory.get_vaults()
    trader_A = vaults[0]
    # FIXME: separate the Bitcoin backends !!
    bitcoind = trader_A.bitcoind
    reused_address = trader_A.getnewaddress()
    # Concurrent sends to the same address should be fine
    for _ in range(3):
        bitcoind.pay_to(reused_address, 12)
    wait_for(lambda: len(trader_A.vaults) == 3)
    for vault in vaults:
        wait_for(lambda: all(v["emergency_signed"] and v["unvault_signed"]
                             and v["unvault_secure"] for v in vault.vaults))

    # Now test address reuse after a vault has been spent
    # We'll spend this one
    v = random.choice(trader_A.vaults)
    # And the second trader will sign with us the spend
    trader_B = vaults[1]
    # FIXME hardcoded fees..
    spend_amount = 12 * COIN - 50000
    # We choose a valid address..
    address = random.choice(trader_A.acked_addresses)
    trader_A.initiate_spend(v, spend_amount, address)
    sigB = trader_B.accept_spend(v["txid"], spend_amount, address)
    pubkeyB = CKey(trader_B.vaults[0]["privkey"]).pub
    tx = trader_A.complete_spend(v, pubkeyB, sigB, spend_amount, address)
    bitcoind.broadcast_and_mine(b2x(v["unvault_tx"].serialize()))
    # At this point we should have remarked the spend, and have either
    # broadcast the cancel_tx, or removed the vault.
    wait_for(lambda: all(len(trader.vaults) == 2 for trader in [trader_A,
                         trader_B]))
    # Generate 5 blocks for the locktime !
    addr = bitcoind.getnewaddress()
    bitcoind.generatetoaddress(5, addr)
    bitcoind.broadcast_and_mine(b2x(tx.serialize()))
    # Creating new vaults should to this address should still be fine
    for _ in range(3):
        bitcoind.pay_to(reused_address, 8)
    # 3 - 1 + 3
    wait_for(lambda: all(len(trader.vaults) == 5 for trader in [trader_A,
                         trader_B]))
    for trader in [trader_A, trader_B]:
        wait_for(lambda: all(v["emergency_signed"] and v["unvault_signed"]
                             and v["unvault_secure"]
                             for v in trader.vaults))


def test_tx_chain_sync(vault_factory):
    """Test all vaults will exchange signatures for all transactions"""
    vaults = vault_factory.get_vaults()
    # FIXME: separate the Bitcoin backends !!
    bitcoind = vaults[0].bitcoind
    # Sending funds to any vault address will be remarked by anyone
    for vault in vaults:
        for _ in range(2):
            bitcoind.pay_to(vault.getnewaddress(), 10)
    wait_for(lambda: all(len(v.vaults) == 8 for v in vaults))
    wait_for(lambda: all(v["emergency_signed"] for v in vault.vaults))
    wait_for(lambda: all(v["unvault_signed"] for v in vault.vaults))
    assert all(v["unvault_secure"] for v in vault.vaults)
    # We can broadcast the unvault tx for any vault
    vault = random.choice(vaults)
    for v in vault.vaults:
        bitcoind.broadcast_and_mine(b2x(v["unvault_tx"].serialize()))
    wait_for(lambda: all(len(v.vaults) == 0 for v in vaults))


def test_cancel_unvault(vault_factory):
    """Test the unvault cancelation (cancel_tx *AND* emer_unvault_tx)"""
    vaults = vault_factory.get_vaults()
    # FIXME: separate the Bitcoin backends !!
    bitcoind = vaults[0].bitcoind
    # Sending funds to any vault address will be remarked by anyone
    for vault in vaults:
        bitcoind.pay_to(vault.getnewaddress(), 10)
    wait_for(lambda: all(len(v.vaults) == len(vaults) for v in vaults))
    wait_for(lambda: all(v["emergency_signed"] for v in vault.vaults))
    wait_for(lambda: all(v["unvault_signed"] for v in vault.vaults))
    assert all(v["unvault_secure"] for v in vault.vaults)
    vault = random.choice(vaults)
    # Send some cancel transaction, they pay to the same script, but the old
    # vault is deleted from our view
    for i in [0, 1]:
        bitcoind.broadcast_and_mine(b2x(vault.vaults[i]["unvault_tx"]
                                        .serialize()))
        bitcoind.broadcast_and_mine(b2x(vault.vaults[i]["cancel_tx"]
                                        .serialize()))
    wait_for(lambda: all(len(v.vaults) == 4 for v in vaults))
    # We should exchange all the signatures for the new vault !
    wait_for(lambda: all(v["emergency_signed"] for v in vault.vaults))
    wait_for(lambda: all(v["unvault_signed"] for v in vault.vaults))
    assert all(v["unvault_secure"] for v in vault.vaults)
    # Send some emergency transactions, this time no new vault created !
    for i in [2, 3]:
        bitcoind.broadcast_and_mine(b2x(vault.vaults[i]["unvault_tx"]
                                        .serialize()))
        bitcoind.broadcast_and_mine(b2x(vault.vaults[i]["unvault_emer_tx"]
                                        .serialize()))
    wait_for(lambda: all(len(v.vaults) == 4 for v in vaults))


def test_spend_creation(vault_factory):
    """Test that the signature exchange between the traders and cosigner leads
    to a well-formed spend_tx."""
    vaults = vault_factory.get_vaults()
    vaultA, vaultB = vaults[0], vaults[1]
    # FIXME: separate the Bitcoin backends !!
    bitcoind = vaultA.bitcoind
    bitcoind.pay_to(vaultA.getnewaddress(), 10)
    wait_for(lambda: all(len(v.vaults) == 1 for v in vaults))
    wait_for(lambda: all(v["emergency_signed"] for v in vaultA.vaults))
    wait_for(lambda: all(v["unvault_signed"] for v in vaultA.vaults))
    # Try to spend from the newly created vault
    v = vaultA.vaults[0]
    # FIXME
    spend_amount = 10 * COIN - 50000
    # Choose a valid address
    address = random.choice(vaultA.acked_addresses)
    vaultA.initiate_spend(v, spend_amount, address)
    sigB = vaultB.accept_spend(v["txid"], spend_amount, address)
    pubkeyB = CKey(vaultB.vaults[0]["privkey"]).pub
    tx = vaultA.complete_spend(v, pubkeyB, sigB, spend_amount, address)
    bitcoind.broadcast_and_mine(b2x(v["unvault_tx"].serialize()))
    addr = bitcoind.getnewaddress()
    # Timelock
    bitcoind.generatetoaddress(5, addr)
    bitcoind.broadcast_and_mine(b2x(tx.serialize()))
