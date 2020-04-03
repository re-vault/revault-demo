import bitcoin
import random

from bip32 import BIP32
from bitcoin.core import b2x, COIN
from bitcoin.wallet import CKey
from fixtures import *  # noqa: F401,F403
from utils import wait_for


bitcoin.SelectParams("regtest")


def test_vault_address(vault_factory):
    wallets = vault_factory.get_wallets()
    # FIXME: separate the Bitcoin backends !!
    bitcoind = wallets[0].bitcoind
    for wallet in wallets:
        # It's burdensome to our xpub to be None in the list, but it allows us
        # to know which of the stakeholders we are, so..
        all_xpubs = [keychain.get_master_xpub() if keychain
                     else wallet.our_bip32.get_master_xpub()
                     for keychain in wallet.keychains]
        # bitcoind should always return the same address as us
        for i in range(3):
            wallet_first_address = wallet.getnewaddress()
            bitcoind_first_address = bitcoind.addmultisigaddress(4, [
                b2x(BIP32.from_xpub(xpub).get_pubkey_from_path([i]))
                for xpub in all_xpubs
            ])["address"]
            assert wallet_first_address == bitcoind_first_address


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
    wallet = vault_factory.get_wallets()[0]
    # GET emergency feerate
    feerate = wallet.sigserver.get_feerate("emergency", txid="high_entropy")
    # sats/vbyte, if it's less there's something going on !
    assert feerate >= 1


def test_signatures_posting(vault_factory):
    """Test that we can send signatures to the sig server."""
    wallet = vault_factory.get_wallets()[0]
    wallet.sigserver.send_signature("00af", "aa56")


def test_funds_polling(vault_factory):
    """Test that we are aware of the funds we receive."""
    wallet = vault_factory.get_wallets()[0]
    # FIXME: separate the Bitcoin backends !!
    bitcoind = wallet.bitcoind
    assert len(wallet.vaults) == 0
    # Send new funds to it
    for i in range(3):
        bitcoind.pay_to(wallet.getnewaddress(), 10)
    wait_for(lambda: len(wallet.vaults) == 3)
    # Retry with a gap
    for _ in range(20):
        wallet.getnewaddress()
    for i in range(2):
        bitcoind.pay_to(wallet.getnewaddress(), 10)
    wait_for(lambda: len(wallet.vaults) == 5)


def test_emergency_sig_sharing(vault_factory):
    """Test that we share the emergency transaction signature."""
    wallet = vault_factory.get_wallets()[0]
    # FIXME: separate the Bitcoin backends !!
    bitcoind = wallet.bitcoind
    assert len(wallet.vaults) == 0
    # Send new funds to it
    bitcoind.pay_to(wallet.getnewaddress(), 10)
    wait_for(lambda: len(wallet.vaults) == 1)
    wait_for(lambda:
             wallet.vaults[0]["emergency_sigs"][wallet.keychains.index(None)]
             is not None)


def test_emergency_tx_sync(vault_factory):
    """Test that we correctly share and gather emergency transactions
    signatures."""
    wallets = vault_factory.get_wallets()
    # FIXME: separate the Bitcoin backends !!
    bitcoind = wallets[0].bitcoind
    # Sending funds to any vault address will be remarked by anyone
    for wallet in wallets:
        bitcoind.pay_to(wallet.getnewaddress(), 10)
    wait_for(lambda: all(len(wallet.vaults) == len(wallets)
                         for wallet in wallets))
    for wallet in wallets:
        wait_for(lambda: all(vault["emergency_signed"]
                             for vault in wallet.vaults))
    # All nodes should have the same emergency transactions
    for i in range(len(wallets) - 1):
        first_emer_txs = [v["emergency_tx"] for v in wallets[i].vaults]
        second_emer_txs = [v["emergency_tx"] for v in wallets[i + 1].vaults]
        for tx in first_emer_txs:
            assert tx == second_emer_txs[first_emer_txs.index(tx)]


def test_emergency_broadcast(vault_factory):
    """Test that the emergency transactions we create are valid and can be
    broadcast. Test that if one is broadcast, all are."""
    wallets = vault_factory.get_wallets()
    # FIXME: separate the Bitcoin backends !!
    bitcoind = wallets[0].bitcoind
    # Sending funds to any vault address will be remarked by anyone
    for wallet in wallets:
        for _ in range(2):
            bitcoind.pay_to(wallet.getnewaddress(), 10)
    for wallet in wallets:
        wait_for(lambda: len(wallet.vaults) == 2 * len(wallets))
        wait_for(lambda: all(v["emergency_signed"] for v in wallet.vaults))
    wallet = random.choice(wallets)
    vault = random.choice(wallet.vaults)
    bitcoind.broadcast_and_mine(vault["emergency_tx"].serialize().hex())
    wait_for(lambda: wallet.stopped)


def test_vault_address_reuse(vault_factory):
    """Test that we are still safe if coins are sent to an already used vault.
    """
    wallets = vault_factory.get_wallets()
    trader_A = wallets[0]
    # FIXME: separate the Bitcoin backends !!
    bitcoind = trader_A.bitcoind
    reused_address = trader_A.getnewaddress()
    # Concurrent sends to the same address should be fine
    for _ in range(3):
        bitcoind.pay_to(reused_address, 12)
    wait_for(lambda: len(trader_A.vaults) == 3)
    for wallet in wallets:
        wait_for(lambda: all(v["emergency_signed"] and v["unvault_signed"]
                             and v["unvault_secure"] for v in wallet.vaults))

    # Now test address reuse after a vault has been spent
    # We'll spend this one
    v = random.choice(trader_A.vaults)
    # And the second trader will sign with us the spend
    trader_B = wallets[1]
    # FIXME hardcoded fees..
    spend_amount = 12 * COIN - 50000
    # We choose a valid address..
    addresses = {
        random.choice(trader_A.acked_addresses): spend_amount,
    }
    trader_A.initiate_spend(v, addresses)
    sigB = trader_B.accept_spend(v["txid"], addresses)
    pubkeyB = CKey(trader_B.vaults[0]["privkey"]).pub
    tx = trader_A.complete_spend(v, pubkeyB, sigB, addresses)
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
    wallets = vault_factory.get_wallets()
    # FIXME: separate the Bitcoin backends !!
    bitcoind = wallets[0].bitcoind
    # Sending funds to any vault address will be remarked by anyone
    for wallet in wallets:
        for _ in range(2):
            bitcoind.pay_to(wallet.getnewaddress(), 10)
    wait_for(lambda: all(len(wallet.vaults) == 8 for wallet in wallets))
    for wallet in wallets:
        wait_for(lambda: all(v["emergency_signed"] for v in wallet.vaults))
        wait_for(lambda: all(v["unvault_signed"] for v in wallet.vaults))
    assert all(v["unvault_secure"] for v in wallet.vaults)
    # We can broadcast the unvault tx for any vault
    vault = random.choice(wallets)
    for v in vault.vaults:
        bitcoind.broadcast_and_mine(b2x(v["unvault_tx"].serialize()))
    wait_for(lambda: all(len(w.vaults) == 0 for w in wallets))


def test_cancel_unvault(vault_factory):
    """Test the unvault cancelation (cancel_tx *AND* emer_unvault_tx)"""
    wallets = vault_factory.get_wallets()
    # FIXME: separate the Bitcoin backends !!
    bitcoind = wallets[0].bitcoind
    # Sending funds to any vault address will be remarked by anyone
    for wallet in wallets:
        bitcoind.pay_to(wallet.getnewaddress(), 10)
    wait_for(lambda: all(len(w.vaults) == len(wallets) for w in wallets))
    for wallet in wallets:
        wait_for(lambda: all(v["emergency_signed"] for v in wallet.vaults))
        wait_for(lambda: all(v["unvault_signed"] for v in wallet.vaults))
        assert all(v["unvault_secure"] for v in wallet.vaults)
    wallet = random.choice(wallets)

    # Send some cancel transaction, they pay to the same script, but the old
    # vault is deleted from our view
    for i in [0, 1]:
        bitcoind.broadcast_and_mine(b2x(wallet.vaults[i]["unvault_tx"]
                                        .serialize()))
        bitcoind.broadcast_and_mine(b2x(wallet.vaults[i]["cancel_tx"]
                                        .serialize()))
    wait_for(lambda: all(len(w.vaults) == 4 for w in wallets))
    # We should exchange all the signatures for the new vault !
    wait_for(lambda: all(v["emergency_signed"] for v in wallet.vaults))
    wait_for(lambda: all(v["unvault_signed"] for v in wallet.vaults))
    assert all(v["unvault_secure"] for v in wallet.vaults)

    # Send some emergency transactions, this time no new vault created !
    for i in [2, 3]:
        bitcoind.broadcast_and_mine(b2x(wallet.vaults[i]["unvault_tx"]
                                        .serialize()))
        bitcoind.broadcast_and_mine(b2x(wallet.vaults[i]["unvault_emer_tx"]
                                        .serialize()))
    wait_for(lambda: all(len(w.vaults) == 4 for w in wallets))


def test_spend_creation(vault_factory):
    """Test that the signature exchange between the traders and cosigner leads
    to a well-formed spend_tx."""
    wallets = vault_factory.get_wallets()
    trader_A, trader_B = wallets[0], wallets[1]
    # FIXME: separate the Bitcoin backends !!
    bitcoind = trader_B.bitcoind
    bitcoind.pay_to(trader_A.getnewaddress(), 10)
    wait_for(lambda: all(len(w.vaults) == 1 for w in wallets))
    wait_for(lambda: all(v["emergency_signed"] for v in trader_A.vaults))
    wait_for(lambda: all(v["unvault_signed"] for v in trader_B.vaults))
    assert all(v["unvault_secure"] for v in trader_A.vaults)

    # Try to spend from the newly created vault
    vault = trader_A.vaults[0]
    # FIXME hardcoded fees..
    spend_amount = 10 * COIN - 50000
    # We choose a valid address..
    addresses = {
        random.choice(trader_A.acked_addresses): spend_amount,
    }
    # The first trader creates the tx, signs it, pass both the tx and sig to B
    trader_A.initiate_spend(vault, addresses)
    # B hands his signature to A
    sigB = trader_B.accept_spend(vault["txid"], addresses)
    pubkeyB = CKey(trader_B.vaults[0]["privkey"]).pub
    # Then A forms the transaction and tells everyone, we can broadcast it.
    tx = trader_A.complete_spend(vault, pubkeyB, sigB, addresses)
    bitcoind.broadcast_and_mine(b2x(vault["unvault_tx"].serialize()))
    # At this point we should have remarked the spend, and have either
    # broadcast the cancel_tx, or removed the vault.
    wait_for(lambda: all(len(trader.vaults) == 0 for trader in [trader_A,
                         trader_B]))
    # Generate 5 blocks for the locktime !
    addr = bitcoind.getnewaddress()
    bitcoind.generatetoaddress(5, addr)
    bitcoind.broadcast_and_mine(b2x(tx.serialize()))
