import bitcoin.rpc

from bip32 import BIP32
from bitcoin.wallet import CBitcoinAddress
from .transactions import (
    vault_txout,
)


class Vault:
    """The vault from the viewpoint of one of the stakeholders.

    Allows to derive the next key of the HD wallets of all the stakeholders, to
    deterministically derive each vault.
    Builds and signs all the necessary transactions when spending from the
    vault.
    """
    def __init__(self, xpriv, xpubs, server_pubkey, emergency_pubkeys,
                 bitcoin_conf_path, current_index=0):
        """
        We need the xpub of all the other stakeholders to derive their pubkeys.

        :param xpriv: Who am I ? Has to correspond to one of the following
                      xpub. As str.
        :param xpubs: A list of the xpub of all the stakeholders (as str), in
                      the following order: 1) first trader 2) second trader
                      3) first "normie" stakeholder 4) second "normie"
                      stakeholder.
        :param server_pubkey: The public key of the co-signing server.
        :param emergency_pubkeys: A list of the four offline keys of the
                                  stakeholders, as bytes.
        :param bitcoin_conf_path: Path to bitcoin.conf.
        """
        assert len(xpubs) == 4
        self.our_bip32 = BIP32.from_xpriv(xpriv)
        self.keychains = []
        for xpub in xpubs:
            if xpub != self.our_bip32.get_master_xpub():
                self.keychains.append(BIP32.from_xpub(xpub))
            else:
                self.keychains.append(None)
        self.server_pubkey = server_pubkey
        self.emergency_pubkeys = emergency_pubkeys
        self.current_index = current_index
        self.bitcoind = bitcoin.rpc.RawProxy(btc_conf_file=bitcoin_conf_path)
        # FIXME: We need something more robust than assuming other stakeholders
        # won't be more out of sync than +100 of the index.
        for i in range(current_index, current_index + 100):
            pubkeys = self.get_pubkeys(i)
            self.watch_output(vault_txout(pubkeys, 0))

    def get_pubkeys(self, index):
        """Get all the pubkeys for this {index}.

        :return: A list of the four pubkeys for this bip32 derivation index.
        """
        pubkeys = []
        for keychain in self.keychains:
            if keychain:
                pubkeys.append(keychain.get_pubkey_from_path([index]))
            else:
                pubkeys.append(self.our_bip32.get_pubkey_from_path([index]))
        return pubkeys

    def watch_output(self, txo):
        """Import this output as watchonly to bitcoind.

        :param txo: The output to watch, a CTxOutput.
        """
        addr = str(CBitcoinAddress.from_scriptPubKey(txo.scriptPubKey))
        self.bitcoind.importaddress(addr, "vaultaic", True)

    def getnewaddress(self):
        """Get the next vault address, we bump the derivation index.

        :return: (str) The next vault address.
        """
        pubkeys = self.get_pubkeys(self.current_index)
        # Bump afterwards..
        self.current_index += 1
        txo = vault_txout(pubkeys, 0)
        return str(CBitcoinAddress.from_scriptPubKey(txo.scriptPubKey))
