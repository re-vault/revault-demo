import bitcoin.rpc
import requests
import threading

from bip32 import BIP32
from bitcoin.core import b2x, lx, COIN
from bitcoin.wallet import CBitcoinAddress
from decimal import Decimal, getcontext
from .transactions import (
    vault_txout, create_and_sign_emergency_vault_tx, form_emergency_vault_tx,
    get_transaction_size,
)


class Vault:
    """The vault from the viewpoint of one of the stakeholders.

    Allows to derive the next key of the HD wallets of all the stakeholders, to
    deterministically derive each vault.
    Builds and signs all the necessary transactions when spending from the
    vault.
    """
    def __init__(self, xpriv, xpubs, server_pubkey, emergency_pubkeys,
                 bitcoin_conf_path, sigserver_url, current_index=0):
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
        :param sigserver_url: The url of the server to post / get the sigs from
                              other stakeholders.
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
        # FIXME: Use the sig server to adjust the gap limit
        self.max_index = current_index + 20
        # Needs to be acquired to access any of the above
        self.keys_lock = threading.Lock()

        self.bitcoind = bitcoin.rpc.RawProxy(btc_conf_file=bitcoin_conf_path)
        # Needs to be acquired to send RPC commands
        self.bitcoind_lock = threading.Lock()

        # No lock we don't ever modify it
        self.sigserver_url = sigserver_url
        if self.sigserver_url.endswith('/'):
            self.sigserver_url = self.sigserver_url[:-1]
        self.update_watched_addresses()

        # We keep track of each vault, represented as
        # {
        #   "txid": "hex",
        #   "vout": n,
        #   "amount": n,
        #   "pubkeys": [pk1, pk2, pk3, pk4],
        #   "emergency_tx": CTransaction,
        #   "emergency_signed": bool,
        #   "unvaul_tx": CTransaction or None,
        #   "unvault_cancel_tx": CTransaction or None,
        #   "unvault_emergency_tx": CTransaction or None,
        # }
        # The amount is in satoshis.
        self.vaults = []
        self.vaults_lock = threading.Lock()

        # Small bitcoin amounts don't play well..
        getcontext().prec = 8

        # Poll for funds until we die
        self.poller_stop = threading.Event()
        self.poller = threading.Thread(target=self.poll_for_funds)
        self.poller.start()

        self.update_emer_stop = threading.Event()
        self.update_emer_thread =\
            threading.Thread(target=self.update_all_emergency_signatures)

    def __del__(self):
        # Stop the thread polling bitcoind
        self.poller_stop.set()
        if self.poller is not None:
            self.poller.join()
        # Stop the RPC connection to bitcoind
        self.bitcoind_lock.acquire()
        self.bitcoind.close()
        self.bitcoind_lock.release()
        # Stop the thread updating emergency transactions
        self.update_emer_stop.set()
        if self.update_emer_thread is not None:
            try:
                self.update_emer_thread.join()
            except RuntimeError:
                # Already dead
                pass

    def get_pubkeys(self, index):
        """Get all the pubkeys for this {index}.

        :return: A list of the four pubkeys for this bip32 derivation index.
        """
        pubkeys = []
        self.keys_lock.acquire()
        for keychain in self.keychains:
            if keychain:
                pubkeys.append(keychain.get_pubkey_from_path([index]))
            else:
                pubkeys.append(self.our_bip32.get_pubkey_from_path([index]))
        self.keys_lock.release()
        return pubkeys

    def watch_output(self, txo):
        """Import this output as watchonly to bitcoind.

        :param txo: The output to watch, a CTxOutput.
        """
        addr = str(CBitcoinAddress.from_scriptPubKey(txo.scriptPubKey))
        self.bitcoind_lock.acquire()
        # FIXME: Optimise this...
        self.bitcoind.importaddress(addr, "vaultaic", True)
        self.bitcoind_lock.release()

    def update_watched_addresses(self):
        """Update the watchonly addresses"""
        for i in range(self.current_index, self.max_index):
            pubkeys = self.get_pubkeys(i)
            self.watch_output(vault_txout(pubkeys, 0))

    def get_vault_address(self, index):
        """Get the vault address for index {index}"""
        pubkeys = self.get_pubkeys(index)
        txo = vault_txout(pubkeys, 0)
        return str(CBitcoinAddress.from_scriptPubKey(txo.scriptPubKey))

    def getnewaddress(self):
        """Get the next vault address, we bump the derivation index.

        :return: (str) The next vault address.
        """
        addr = self.get_vault_address(self.current_index)
        # Bump afterwards..
        self.current_index += 1
        self.max_index += 1
        self.update_watched_addresses()
        return addr

    def get_emergency_feerate(self, txid):
        """Get the feerate for the emergency transaction.

        :param txid: The emergency transaction id, as str.
        :return: The feerate in **sat/VByte**, as int.
        """
        r = requests.get("{}/emergency_feerate/{}".format(self.sigserver_url,
                                                          txid))
        if not r.status_code == 200:
            raise Exception("The sigserver returned with '{}', saying '{}'"
                            .format(r.status_code, r.text))
        btc_perkvb = Decimal(r.json()["feerate"])
        # Explicit conversion to sat per virtual byte
        return int(btc_perkvb * Decimal(COIN) / Decimal(1000))

    def guess_index(self, vault_address):
        """Guess the index used to derive the 4 pubkeys used in this 4of4.

        :param vault_address: (str) The vault P2WSH address.

        :return: The index.
        """
        for index in range(self.max_index):
            if vault_address == self.get_vault_address(index):
                return index
        raise Exception("No such vault script with our known pubkeys !")

    def add_new_vault(self, output):
        """Add a new vault output to our list.

        :param output: A dict corresponding to an entry of `listunspent`.
        """
        vault = {
            "txid": output["txid"],
            "vout": output["vout"],
            # This amount is in BTC, we want sats
            "amount": int(Decimal(output["amount"]) * Decimal(COIN)),
            "pubkeys": [],
            # For convenience
            "address": output["address"],
            "emergency_tx": None,
            "emergency_signed": False,
            "unvaul_tx": None,
            "unvault_emergency_tx": None,
        }
        index = self.guess_index(vault["address"])
        vault["pubkeys"] = self.get_pubkeys(index)
        privkey = self.our_bip32.get_privkey_from_path([index])
        # Dummy amount to get the feerate..
        amount = bitcoin.core.COIN
        dummy_tx, _ = \
            create_and_sign_emergency_vault_tx(lx(vault["txid"]),
                                               vault["vout"], vault["pubkeys"],
                                               amount, vault["amount"],
                                               self.emergency_pubkeys, [])
        tx_size = get_transaction_size(dummy_tx)
        fees = self.get_emergency_feerate(b2x(dummy_tx.GetTxid())) * tx_size
        amount = vault["amount"] - fees
        vault["emergency_tx"], sigs = \
            create_and_sign_emergency_vault_tx(lx(vault["txid"]),
                                               vault["vout"], vault["pubkeys"],
                                               amount, vault["amount"],
                                               self.emergency_pubkeys,
                                               [privkey])
        self.send_signature(b2x(vault["emergency_tx"].GetTxid()), sigs[0])
        self.vaults.append(vault)

    def poll_for_funds(self):
        """Polls bitcoind to check for received funds.

        If we just went to know of the possession of a new output, it will
        construct the corresponding emergency transaction and spawn a thread
        to fetch emergency transactions signatures.
        """
        while not self.poller_stop.wait(5.0):
            known_outputs = [v["txid"] for v in self.vaults]
            self.bitcoind_lock.acquire()
            vault_utxos = [utxo for utxo in self.bitcoind.listunspent()
                           # FIXME: This is a hack, better keeping track of
                           # known vault addresses.
                           if not utxo["spendable"]
                           and utxo["txid"] not in known_outputs]
            self.bitcoind_lock.release()
            for output in vault_utxos:
                self.vaults_lock.acquire()
                self.add_new_vault(output)
                self.vaults_lock.release()
            # Ok we updated our owned outputs, restart the emergency
            # transactions gathering with the updated vaults list
            self.update_emer_stop.set()
            if self.update_emer_thread is not None:
                try:
                    self.update_emer_thread.join()
                except RuntimeError:
                    # Already dead
                    pass
            self.update_emer_thread.start()

    def send_signature(self, txid, sig):
        """Send the signature {sig} for tx {txid} to the sig server."""
        if isinstance(sig, bytes):
            sig = sig.hex()
        elif not isinstance(sig, str):
            raise Exception("The signature must be either bytes or a valid hex"
                            " string")
        # Who am I ?
        stakeholder_id = self.keychains.index(None) + 1
        r = requests.post("{}/sig/{}/{}".format(self.sigserver_url, txid,
                                                stakeholder_id),
                          data={"sig": sig})
        if not r.status_code == 201:
            raise Exception("stakeholder #{}: Could not send sig '{}' for"
                            " txid {}.".format(stakeholder_id, sig, txid))

    def get_signature(self, txid, stakeholder_id):
        """Request a signature to the signature server.

        :param txid: The txid of the transaction we're interested in.
        :param stakeholder_id: Which stakeholder's sig do we need.

        :return: The signature as bytes, or None if not found.
        """
        r = requests.get("{}/sig/{}/{}".format(self.sigserver_url, txid,
                                               stakeholder_id))
        if r.status_code == 200:
            return bytes.fromhex(r.json()["sig"])
        elif r.status_code == 404:
            return None
        else:
            raise Exception("Requesting stakeholder #{}'s signature for tx "
                            "{}, response {}".format(stakeholder_id, txid,
                                                     r.text))

    def update_emergency_signatures(self, vault):
        """Don't stop polling the sig server until we have all the sigs.

        :vault: The dictionary representing the vault we are fetching the
                emergency signatures for.
        """
        # The signatures ordered like stk1, stk2, stk3, stk4
        sigs = [None, None, None, None]
        txid = b2x(vault["emergency_tx"].GetTxid())
        while None in sigs and not self.update_emer_stop.wait(1):
            for i in range(1, 4):
                if sigs[i - 1] is None:
                    sigs[i - 1] = self.get_signature(txid, i)
        # Only populate the sigs if we got them all, not if master told us to
        # stop.
        if not self.update_emer_stop.wait(0.0):
            # self.vaults_lock.acquire()
            vault["emergency_tx"] = \
                form_emergency_vault_tx(vault["emergency_tx"],
                                        vault["pubkeys"], sigs)
            vault["emergency_signed"] = True
            # self.vaults_lock.release()

    def update_all_emergency_signatures(self):
        """Poll the server for the signatures of all vaults' emergency tx."""
        threads = []
        # Don't reserve the vaults lock for an indefinite amount of time
        for vault in self.vaults:
            if self.update_emer_stop.wait(0.0):
                return
            if not vault["emergency_signed"]:
                t = threading.Thread(
                    target=self.update_emergency_signatures, args=[vault])
                t.start()
                threads.append(t)
        for t in threads:
            if self.update_emer_stop.wait(0.0):
                return
            t.join()
