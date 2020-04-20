import bitcoin.rpc
import threading
import time

from bitcoin.core import COIN
from decimal import Decimal


class BitcoindApi:
    """A higher-level wrapper around bitcoind RPC."""
    def __init__(self, conf_file):
        """
        :param conf_file: The bitcoind configuration file.
        """
        self.bitcoind = bitcoin.rpc.RawProxy(btc_conf_file=conf_file)
        # Needs to be acquired to send RPC commands
        self.bitcoind_lock = threading.Lock()
        self.mocked_feerate = None

    def __del__(self):
        self.close()

    def close(self):
        """Close the connection to bitcoind."""
        self.bitcoind.close()

    def call(self, name, *args):
        """Exception-safe lock handling."""
        err = None
        f = getattr(self.bitcoind, name)

        self.bitcoind_lock.acquire()
        try:
            res = f(*args)
        except Exception as e:
            err = e
        self.bitcoind_lock.release()

        if err is not None:
            raise err
        return res

    def mock_feerate(self, feerate):
        """sat/vbyte !!"""
        self.mocked_feerate = feerate

    def importmultiextended(self, xpubs, birthdate, min_index, max_index):
        """Import a 4-of-4 P2WSH descriptor with 4 xpubs (m/0).

        :param xpubs: A list of encoded extended pubkeys as str.
        :param birthdate: The timestamp at which the keys were created.
        :param min_index: The derivation index to start scanning for.
        :param max_index: The derivation index to end scanning for.
        """
        desc = "wsh(multi(4,{}/*,{}/*,{}/*,{}/*))".format(*xpubs)
        checksum = self.call("getdescriptorinfo", desc)["checksum"]
        res = self.call("importmulti", [{
            "desc": "{}#{}".format(desc, checksum),
            "timestamp": birthdate,
            "range": [min_index, max_index],
            "watchonly": True,
            "label": "revault_vault"
        }])
        if not res[0]["success"]:
            raise Exception("Failed to import xpubs. "
                            "Descriptor: {}, result: {}"
                            .format(desc, str(res)))

    def listunspent(self, minconf=1, maxconf=9999999, addresses=None,
                    unsafe=True):
        return self.call("listunspent", minconf, maxconf, addresses, unsafe)

    def gettransaction(self, txid):
        return self.call("gettransaction", txid)

    def getrawtransaction(self, txid, decode=False):
        try:
            tx = self.call("getrawtransaction", txid, decode)
            return tx
        except bitcoin.rpc.JSONRPCError:
            # In case this is a wallet transaction
            tx = self.call("gettransaction", txid)
            if decode:
                return self.decoderawtransaction(tx["hex"])
            return tx["hex"]

    def decoderawtransaction(self, hex):
        return self.call("decoderawtransaction", hex)

    def sendtoaddress(self, address, amount):
        return self.call("sendtoaddress", address, amount)

    def getrawmempool(self):
        return self.call("getrawmempool")

    def addmultisigaddress(self, num, pubkeys):
        return self.call("addmultisigaddress", num, pubkeys)

    def generatetoaddress(self, num, address):
        return self.call("generatetoaddress", num, address)

    def getnewaddress(self):
        return self.call("getnewaddress")

    def sendrawtransaction(self, tx):
        return self.call("sendrawtransaction", tx)

    def importaddress(self, address, label, rescan=True):
        return self.call("importaddress", address, label, rescan)

    def dumpprivkey(self, address):
        return self.call("dumpprivkey", address)

    def getfeerate(self, type=None):
        """This mimics the sig server behaviour.

        :returns: The feerate as **sat/vbyte**
        """
        if self.mocked_feerate is not None:
            return self.mocked_feerate

        if type == "emergency":
            res = self.call("estimatesmartfee", 2,
                            "CONSERVATIVE")["feerate"] * Decimal(10)
        elif type == "cancel":
            res = self.call("estimatesmartfee", 2,
                            "CONSERVATIVE")["feerate"] * Decimal(5)
        else:
            res = self.call("estimatesmartfee", 3, "CONSERVATIVE")["feerate"]
        return res * Decimal(COIN) / Decimal(1000)

    def mine(self, txid):
        while txid not in self.getrawmempool():
            time.sleep(0.5)
        addr = self.call("getnewaddress")
        self.call("generatetoaddress", 1, addr)

    def broadcast_and_mine(self, tx):
        """A routine used in the tests"""
        txid = self.sendrawtransaction(tx)
        self.mine(txid)
        return txid

    def pay_to(self, address, amount):
        """A helper for the functional tests.."""
        addr = self.call("getnewaddress")
        while self.bitcoind.getbalance() < amount + 1:
            self.call("generatetoaddress", 1, addr)
        txid = self.sendtoaddress(address, amount)
        self.mine(txid)
        return txid

    def assertmempoolaccept(self, txs):
        """Helper for sanity checks."""
        res = self.call("testmempoolaccept", txs)
        if not all(tx["allowed"] for tx in res):
            raise Exception("testmempoolaccept returned {} for {}"
                            .format(res, txs))

    def tx_size(self, tx):
        return self.decoderawtransaction(tx.serialize().hex())["vsize"]
