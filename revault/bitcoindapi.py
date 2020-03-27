import bitcoin.rpc
import threading
import time


class BitcoindApi:
    """A higher-level wrapper around bitcoind RPC."""
    def __init__(self, conf_file):
        """
        :param conf_file: The bitcoind configuration file.
        """
        self.bitcoind = bitcoin.rpc.RawProxy(btc_conf_file=conf_file)
        # Needs to be acquired to send RPC commands
        self.bitcoind_lock = threading.Lock()

    def __del__(self):
        self.close()

    def close(self):
        """Close the connection to bitcoind."""
        self.bitcoind.close()

    def importmulti(self, pubkeys, birthdate):
        """Import a 4-of-4 P2WSH descriptor.

        :param pubkeys: The pubkeys to construct the 4-of-4.
        :param birthdate: The timestamp at which the keys were created.
        """
        desc = "wsh(multi(4,{},{},{},{}))".format(*pubkeys)
        # No checksum, we are only ever called at startup before any thread
        checksum = self.bitcoind.getdescriptorinfo(desc)["checksum"]
        res = self.bitcoind.importmulti([{
            "desc": "{}#{}".format(desc, checksum),
            "timestamp": birthdate,
            "watchonly": True,
            "label": "revault_emergency_vault"
        }])
        if not res[0]["success"]:
            raise Exception("Failed to import emergency pubkeys. "
                            "Descriptor: {}, result: {}"
                            .format(desc, str(res)))

    def importmultiextended(self, xpubs, birthdate, min_index, max_index):
        """Import a 4-of-4 P2WSH descriptor with 4 xpubs (m/0).

        :param xpubs: A list of encoded extended pubkeys as str.
        :param birthdate: The timestamp at which the keys were created.
        :param min_index: The derivation index to start scanning for.
        :param max_index: The derivation index to end scanning for.
        """
        desc = "wsh(multi(4,{}/*,{}/*,{}/*,{}/*))".format(*xpubs)
        self.bitcoind_lock.acquire()
        checksum = self.bitcoind.getdescriptorinfo(desc)["checksum"]
        res = self.bitcoind.importmulti([{
            "desc": "{}#{}".format(desc, checksum),
            "timestamp": birthdate,
            "range": [min_index, max_index],
            "watchonly": True,
            "label": "revault_vault"
        }])
        self.bitcoind_lock.release()
        if not res[0]["success"]:
            raise Exception("Failed to import xpubs. "
                            "Descriptor: {}, result: {}"
                            .format(desc, str(res)))

    def listunspent(self):
        self.bitcoind_lock.acquire()
        utxos = self.bitcoind.listunspent()
        self.bitcoind_lock.release()
        return utxos

    def gettransaction(self, txid):
        self.bitcoind_lock.acquire()
        tx = self.bitcoind.gettransaction(txid)
        self.bitcoind_lock.release()
        return tx

    def decoderawtransaction(self, hex):
        self.bitcoind_lock.acquire()
        tx = self.bitcoind.decoderawtransaction(hex)
        self.bitcoind_lock.release()
        return tx

    def sendtoaddress(self, address, amount):
        self.bitcoind_lock.acquire()
        txid = self.bitcoind.sendtoaddress(address, amount)
        self.bitcoind_lock.release()
        return txid

    def getrawmempool(self):
        self.bitcoind_lock.acquire()
        mempool = self.bitcoind.getrawmempool()
        self.bitcoind_lock.release()
        return mempool

    def addmultisigaddress(self, num, pubkeys):
        self.bitcoind_lock.acquire()
        res = self.bitcoind.addmultisigaddress(num, pubkeys)
        self.bitcoind_lock.release()
        return res

    def generatetoaddress(self, num, address):
        self.bitcoind_lock.acquire()
        txids = self.bitcoind.generatetoaddress(num, address)
        self.bitcoind_lock.release()
        return txids

    def getnewaddress(self):
        self.bitcoind_lock.acquire()
        addr = self.bitcoind.getnewaddress()
        self.bitcoind_lock.release()
        return addr

    def sendrawtransaction(self, tx):
        self.bitcoind_lock.acquire()
        txid = self.bitcoind.sendrawtransaction(tx)
        self.bitcoind_lock.release()
        return txid

    def importaddress(self, address, label, rescan=True):
        self.bitcoind_lock.acquire()
        self.bitcoind.importaddress(address, label, rescan)
        self.bitcoind_lock.release()

    def broadcast_and_mine(self, tx):
        """A routine used in the tests"""
        self.bitcoind_lock.acquire()
        txid = self.bitcoind.sendrawtransaction(tx)
        while txid not in self.bitcoind.getrawmempool():
            time.sleep(0.1)
        self.bitcoind.generatetoaddress(1, self.bitcoind.getnewaddress())
        self.bitcoind_lock.release()
        return txid

    def pay_to(self, address, amount):
        """A helper for the functional tests.."""
        self.bitcoind_lock.acquire()
        txid = self.bitcoind.sendtoaddress(address, amount)
        while txid not in self.bitcoind.getrawmempool():
            time.sleep(0.1)
        self.bitcoind.generatetoaddress(1, self.bitcoind.getnewaddress())
        self.bitcoind_lock.release()
        return txid
