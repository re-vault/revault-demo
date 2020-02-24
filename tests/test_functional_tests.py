import bitcoin
import os

from bip32 import BIP32
from bitcoin.core import b2x
from bitcoin.wallet import CKey
from fixtures import *  # noqa: F401,F403
from vaultaic import Vault


bitcoin.SelectParams("regtest")


def test_vault_address(bitcoind):
    # Us
    our_bip32 = BIP32.from_seed(os.urandom(32))
    our_xpriv = our_bip32.get_master_xpriv()
    # Our fellow stakeholders
    others_bip32 = [BIP32.from_seed(os.urandom(32)) for i in range(3)]
    # Let's be the last stakeholder, i.e. the second trader
    all_xpubs = [keychain.get_master_xpub() for keychain in others_bip32] \
        + [our_bip32.get_master_xpub()]
    serv_key = CKey(os.urandom(32))
    emer_keys = [CKey(os.urandom(32)) for i in range(4)]
    vault = Vault(our_xpriv, all_xpubs, serv_key.pub, emer_keys,
                  bitcoind.rpc.__btc_conf_file__)
    # bitcoind should return the same address as us
    for i in range(25):
        vault_first_address = vault.getnewaddress()
        bitcoind_first_address = bitcoind.rpc.addmultisigaddress(4, [
            b2x(BIP32.from_xpub(xpub).get_pubkey_from_path([i]))
            for xpub in all_xpubs
        ])["address"]
        assert vault_first_address == bitcoind_first_address
