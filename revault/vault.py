import bitcoin.rpc
import threading
import time

from bip32 import BIP32
from bitcoin.core import b2x, lx, COIN
from bitcoin.wallet import CBitcoinAddress
from decimal import Decimal, getcontext
from .bitcoindapi import BitcoindApi
from .serverapi import ServerApi
from .transactions import (
    vault_txout, emergency_txout, create_and_sign_emergency_vault_tx,
    form_emergency_vault_tx, get_transaction_size, create_and_sign_unvault_tx,
    create_cancel_tx, sign_cancel_tx, form_cancel_tx, create_emer_unvault_tx,
    sign_emer_unvault_tx, form_emer_unvault_tx
)


class Vault:
    """The vault from the viewpoint of one of the stakeholders.

    Allows to derive the next key of the HD wallets of all the stakeholders, to
    deterministically derive each vault.
    Builds and signs all the necessary transactions when spending from the
    vault.
    """
    def __init__(self, xpriv, xpubs, server_pubkey, emergency_pubkeys,
                 bitcoin_conf_path, sigserver_url, current_index=0,
                 birthdate=None):
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
        :param birthdate: The timestamp at which this wallet has been created.
                          If not passed, will assume newly-created wallet.
        """
        assert len(xpubs) == 4
        self.our_bip32 = BIP32.from_xpriv(xpriv)
        self.keychains = []
        for xpub in xpubs:
            if xpub != self.our_bip32.get_master_xpub():
                self.keychains.append(BIP32.from_xpub(xpub))
            else:
                self.keychains.append(None)
        self.all_xpubs = xpubs
        self.server_pubkey = server_pubkey
        self.emergency_pubkeys = emergency_pubkeys
        # Ok, shitload of indexes. The current one is the lower bound of the
        # range we will import to bitcoind as watchonly. The max one is the
        # upper bond, the current "gen" one is to generate new addresses.
        self.current_index = current_index
        self.current_gen_index = self.current_index
        self.max_index = current_index + 500
        self.index_treshold = self.max_index
        # Needs to be acquired to access any of the above
        self.keys_lock = threading.Lock()

        self.birthdate = int(time.time()) if birthdate is None else birthdate

        self.bitcoind = BitcoindApi(bitcoin_conf_path)

        # First of all, watch the emergency vault
        self.watch_emergency_vault()
        # And store the corresponding address..
        txo = emergency_txout(self.emergency_pubkeys, 0)
        self.emergency_address = str(CBitcoinAddress
                                     .from_scriptPubKey(txo.scriptPubKey))

        if sigserver_url.endswith('/'):
            self.sigserver = ServerApi(sigserver_url[:-1])
        else:
            self.sigserver = ServerApi(sigserver_url)
        self.watched_addresses = []
        self.update_watched_addresses()

        # We keep track of each vault, represented as
        # {
        #FIXME: Add missing fields
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

        self.stopped = False

    def __del__(self):
        if not self.stopped:
            self.stop()

    def stop(self):
        # Stop the thread polling bitcoind
        self.poller_stop.set()
        self.poller.join()
        self.bitcoind.close()
        # Stop the thread updating emergency transactions
        self.update_emer_stop.set()
        if self.update_emer_thread is not None:
            try:
                self.update_emer_thread.join()
            except RuntimeError:
                # Already dead
                pass
        self.stopped = True

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

    def watch_emergency_vault(self):
        """There is only one emergency script"""
        pubkeys = [b2x(pub) for pub in self.emergency_pubkeys]
        self.bitcoind.importmulti(pubkeys, self.birthdate)

    def update_watched_addresses(self):
        """Update the watchonly addresses"""
        # FIXME: ugly
        for i in range(self.current_index, self.max_index):
            pubkeys = self.get_pubkeys(i)
            txo = vault_txout(pubkeys, 0)
            addr = str(CBitcoinAddress.from_scriptPubKey(txo.scriptPubKey))
            if addr not in self.watched_addresses:
                self.watched_addresses.append(addr)
        self.bitcoind.importmultiextended(self.all_xpubs, self.birthdate,
                                          self.current_index, self.max_index)

    def get_vault_address(self, index):
        """Get the vault address for index {index}"""
        pubkeys = self.get_pubkeys(index)
        txo = vault_txout(pubkeys, 0)
        return str(CBitcoinAddress.from_scriptPubKey(txo.scriptPubKey))

    def getnewaddress(self):
        """Get the next vault address, we bump the derivation index.

        :return: (str) The next vault address.
        """
        addr = self.get_vault_address(self.current_gen_index)
        # FIXME: This is too simplistic
        self.current_gen_index += 1
        # Mind the gap ! https://www.youtube.com/watch?v=UOPyGKDQuRk
        if self.current_gen_index > self.index_treshold - 20:
            self.update_watched_addresses()
        return addr

    def guess_index(self, vault_address):
        """Guess the index used to derive the 4 pubkeys used in this 4of4.

        :param vault_address: (str) The vault P2WSH address.

        :return: The index.
        """
        for index in range(self.max_index):
            if vault_address == self.get_vault_address(index):
                return index
        raise Exception("No such vault script with our known pubkeys !")

    def create_sign_emergency(self, vault):
        """Create and return our signature for the vault emergency tx."""
        # Dummy amount to get the feerate..
        amount = bitcoin.core.COIN
        # FIXME: This interface is ugly
        dummy_tx, _ = \
            create_and_sign_emergency_vault_tx(lx(vault["txid"]),
                                               vault["vout"], vault["pubkeys"],
                                               amount, vault["amount"],
                                               self.emergency_pubkeys, [])
        tx_size = get_transaction_size(dummy_tx)
        feerate = self.sigserver.get_feerate("emergency",
                                             b2x(dummy_tx.GetTxid()))
        fees = feerate * tx_size
        amount = vault["amount"] - fees
        vault["emergency_tx"], sigs = \
            create_and_sign_emergency_vault_tx(lx(vault["txid"]),
                                               vault["vout"], vault["pubkeys"],
                                               amount, vault["amount"],
                                               self.emergency_pubkeys,
                                               [vault["privkey"]])
        return sigs[0]

    def create_sign_unvault(self, vault):
        """Create and return our signature for the unvault tx."""
        # Dummy amount to get the feerate..
        dummy_amount = bitcoin.core.COIN
        dumtx, _ = create_and_sign_unvault_tx(lx(vault["txid"]), vault["vout"],
                                              vault["pubkeys"],
                                              self.server_pubkey, dummy_amount,
                                              vault["amount"], [])
        tx_size = get_transaction_size(dumtx)
        feerate = self.sigserver.get_feerate("cancel", b2x(dumtx.GetTxid()))
        unvault_amount = vault["amount"] - feerate * tx_size
        # FIXME: This interface is ugly
        vault["unvault_tx"], unvtx_sigs = \
            create_and_sign_unvault_tx(lx(vault["txid"]), vault["vout"],
                                       vault["pubkeys"], self.server_pubkey,
                                       unvault_amount, vault["amount"],
                                       [vault["privkey"]])
        return unvtx_sigs[0]

    def create_sign_cancel(self, vault):
        """Create and return our signature for the unvault cancel tx."""
        unvault_txid = vault["unvault_tx"].GetTxid()
        dummy_amount = bitcoin.core.COIN
        unvault_amount = vault["unvault_tx"].vout[0].nValue
        assert len(vault["unvault_tx"].vout) == 1
        # We make the cancel_tx pay to the same script, for simplicity
        dummy_tx = create_cancel_tx(unvault_txid, 0, vault["pubkeys"],
                                    dummy_amount)
        tx_size = get_transaction_size(dummy_tx)
        feerate = self.sigserver.get_feerate("cancel", b2x(dummy_tx.GetTxid()))
        cancel_amount = unvault_amount - feerate * tx_size
        vault["cancel_tx"] = create_cancel_tx(unvault_txid, 0,
                                              vault["pubkeys"], cancel_amount)
        # It wants the pubkeys for the prevout script, but they are the same!
        return sign_cancel_tx(vault["cancel_tx"], [vault["privkey"]],
                              vault["pubkeys"], self.server_pubkey,
                              unvault_amount)[0]

    def create_sign_unvault_emer(self, vault):
        """Create and return our signature for the unvault emergency tx."""
        unvault_txid = vault["unvault_tx"].GetTxid()
        dummy_amount = bitcoin.core.COIN
        unvault_amount = vault["unvault_tx"].vout[0].nValue
        # Last one, the emergency_tx
        dummy_tx = create_emer_unvault_tx(unvault_txid, 0,
                                          self.emergency_pubkeys, dummy_amount)
        tx_size = get_transaction_size(dummy_tx)
        feerate = self.sigserver.get_feerate("emergency",
                                             b2x(dummy_tx.GetTxid()))
        emer_amount = unvault_amount - feerate * tx_size
        vault["unvault_emer_tx"] = \
            create_emer_unvault_tx(unvault_txid, 0, self.emergency_pubkeys,
                                   emer_amount)
        return sign_emer_unvault_tx(vault["unvault_emer_tx"],
                                    [vault["privkey"]], vault["pubkeys"],
                                    self.server_pubkey, unvault_amount)[0]

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
            "privkey": None,
            "address": output["address"],
            "emergency_tx": None,
            # Avoid asking them multiple times
            "emergency_sigs": [None, None, None, None],
            "emergency_signed": False,
            "unvaul_tx": None,
            "cancel_tx": None,
            "unvault_emer_tx": None,
            # Are cancel and emer signed ?
            "unvault_secure": False,
        }
        index = self.guess_index(vault["address"])
        vault["pubkeys"] = self.get_pubkeys(index)
        vault["privkey"] = self.our_bip32.get_privkey_from_path([index])
        emer_sig = self.create_sign_emergency(vault)
        _ = self.create_sign_unvault(vault)
        cancel_sig = self.create_sign_cancel(vault)
        unvault_emer_sig = self.create_sign_unvault_emer(vault)
        # Who am I ?
        stk_id = self.keychains.index(None) + 1
        # Send all our sigs but the unvault one, until we are secured
        self.sigserver.send_signature(b2x(vault["emergency_tx"].GetTxid()),
                                      emer_sig, stk_id)
        self.sigserver.send_signature(b2x(vault["cancel_tx"].GetTxid()),
                                      cancel_sig, stk_id)
        self.sigserver.send_signature(b2x(vault["unvault_emer_tx"].GetTxid()),
                                      unvault_emer_sig, stk_id)
        self.vaults.append(vault)

    def poll_for_funds(self):
        """Polls bitcoind to check for received funds.

        If we just went to know of the possession of a new output, it will
        construct the corresponding emergency transaction and spawn a thread
        to fetch emergency transactions signatures.
        """
        while not self.poller_stop.wait(5.0):
            known_outputs = [v["txid"] for v in self.vaults]
            vault_utxos = []
            for utxo in self.bitcoind.listunspent():
                if utxo["address"] in self.watched_addresses \
                        and utxo["txid"] not in known_outputs:
                    vault_utxos.append(utxo)
                elif utxo["address"] == self.emergency_address:
                    # FIXME: Should we put up the red lights here ?
                    tx = self.bitcoind.gettransaction(utxo["txid"])["hex"]
                    prev = self.bitcoind.decoderawtransaction(tx)["vin"][0]
                    self.vaults = [v for v in self.vaults
                                   if v["txid"] != prev["txid"]]
            for output in vault_utxos:
                self.vaults_lock.acquire()
                self.add_new_vault(output)
                self.vaults_lock.release()
                # Do a new bunch of watchonly imports if we get closer to the
                # maximum index we originally derived.
                # FIXME: This doesn't take address reuse into account
                self.current_index += 1
                self.max_index += 1
                if self.current_index > self.index_treshold - 20:
                    self.update_watched_addresses()
            if len(vault_utxos) > 0:
                # Ok we updated our owned outputs, restart the emergency
                # transactions gathering with the updated vaults list
                self.update_emer_stop.set()
                if self.update_emer_thread is not None:
                    try:
                        self.update_emer_thread.join()
                    except RuntimeError:
                        # Already dead
                        pass
                self.update_emer_stop.clear()
                # You cant just restart threads in Python :-(
                del self.update_emer_thread
                self.update_emer_thread = \
                    threading.Thread(target=self.
                                     update_all_emergency_signatures)
                self.update_emer_thread.start()

    def update_emergency_signatures(self, vault):
        """Don't stop polling the sig server until we have all the sigs.

        :vault: The dictionary representing the vault we are fetching the
                emergency signatures for.
        """
        # The signatures ordered like stk1, stk2, stk3, stk4
        txid = b2x(vault["emergency_tx"].GetTxid())
        while None in vault["emergency_sigs"] and \
                not self.update_emer_stop.wait(4.0):
            for i in range(1, 5):
                if vault["emergency_sigs"][i - 1] is None:
                    self.vaults_lock.acquire()
                    vault["emergency_sigs"][i - 1] = \
                        self.sigserver.get_signature(txid, i)
                    self.vaults_lock.release()
        # Only populate the sigs if we got them all, not if master told us to
        # stop.
        if None not in vault["emergency_sigs"]:
            self.vaults_lock.acquire()
            vault["emergency_tx"] = \
                form_emergency_vault_tx(vault["emergency_tx"],
                                        vault["pubkeys"],
                                        vault["emergency_sigs"])
            vault["emergency_signed"] = True
            # FIXME: is deleting sigs from the struct here over optimization ?
            self.vaults_lock.release()

    def update_all_emergency_signatures(self):
        """Poll the server for the signatures of all vaults' emergency tx."""
        if self.update_emer_stop.wait(0.0):
            return
        threads = []
        for vault in self.vaults:
            if not vault["emergency_signed"]:
                t = threading.Thread(
                    target=self.update_emergency_signatures, args=[vault])
                t.start()
                threads.append(t)
        while len(threads) > 0:
            threads.pop().join()
