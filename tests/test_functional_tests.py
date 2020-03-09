import bitcoin
import os
import unittest

from bip32 import BIP32
from bitcoin.core import b2x
from bitcoin.wallet import CKey
from fixtures import *  # noqa: F401,F403
from utils import SIGSERV_URL
from vaultaic import Vault


bitcoin.SelectParams("regtest")


def get_random_vault(bitcoind_conf, our_seed=None, xpubs=None,
                     serv_pubkey=None, emer_pubkeys=None, whoami=1):
    """Create a vault instance."""
    # Us
    if our_seed is None:
        our_seed = os.urandom(32)
    our_bip32 = BIP32.from_seed(our_seed)
    our_xpriv = our_bip32.get_master_xpriv()
    # Our fellow stakeholders
    if xpubs is None:
        others_bip32 = [BIP32.from_seed(os.urandom(32)) for i in range(3)]
        xpubs = [keychain.get_master_xpub() for keychain in others_bip32]
    # Are we one of the traders or a normie stakeholder ?
    if whoami == 1:
        all_xpubs = [our_bip32.get_master_xpub()] + xpubs
    elif whoami == 2:
        all_xpubs = [xpubs[0], [our_bip32.get_master_xpub()]] + xpubs[1:]
    elif whoami == 3:
        all_xpubs = xpubs[:1] + [our_bip32.get_master_xpub(), xpubs[2]]
    elif whoami == 4:
        all_xpubs = xpubs + [our_bip32.get_master_xpub()]
    if serv_pubkey is None:
        serv_pubkey = CKey(os.urandom(32)).pub
    if emer_pubkeys is None:
        emer_pubkeys = [CKey(os.urandom(32)).pub for i in range(4)]
    if not SIGSERV_URL.startswith("http"):
        sigserv_url = "http://{}".format(SIGSERV_URL)
    else:
        sigserv_url = SIGSERV_URL
    return Vault(our_xpriv, all_xpubs, serv_pubkey, emer_pubkeys,
                 bitcoind_conf, sigserv_url)


def test_vault_address(bitcoind):
    for i in range(1, 4):
        vault = get_random_vault(bitcoind.rpc.__btc_conf_file__, whoami=i)
        # It's burdensome to our xpub to be None in the list, but it allows us
        # to know which of the stakeholders we are, so..
        all_xpubs = [keychain.get_master_xpub() if keychain
                     else vault.our_bip32.get_master_xpub()
                     for keychain in vault.keychains]
        # bitcoind should always return the same address as us
        for i in range(3):
            vault_first_address = vault.getnewaddress()
            bitcoind_first_address = bitcoind.rpc.addmultisigaddress(4, [
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
    # GET emergency feerate
    r = sigserv.get("emergency_feerate/{}".format(txid))
    assert r.status_code == 200


@unittest.skipIf(SIGSERV_URL == "", "We want to test against a running Flask"
                                    " instance, not test_client()")
def test_signatures_posting(bitcoind):
    """Test that we can send signatures to the sig server."""
    vault = get_random_vault(bitcoind.rpc.__btc_conf_file__)
    vault.send_signature("00af", "aa56")
