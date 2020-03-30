import bitcoin
import os

from bitcoin.core import lx
from bitcoin.wallet import CKey
from flask import Flask, jsonify

from .transactions import create_spend_tx, sign_spend_tx


class CosigningServer:
    """
    A wrapper around a dead simple server co-signing spend transactions, but
    only once.
    """
    def __init__(self):
        """Uncommon pattern, but a handy one. We setup everything when the
        wrapper is initialized."""
        self.server = Flask(__name__)
        self.privkey = os.urandom(32)
        self.pubkey = CKey(self.privkey).pub
        # List of txids we already signed
        self.already_signed = []
        bitcoin.SelectParams("regtest")
        self.setup_routes()

    def setup_routes(self):
        @self.server.route("/sign/<string:txid>/<string:pub1>/<string:pub2>/"
                           "<string:pub3>/<string:pub4>/<string:address>"
                           "/<int:value>/<int:prev_value>", methods=["GET"])
        def get_signature(txid, pub1, pub2, pub3, pub4,
                          address, value, prev_value):
            """Sign a spend transaction.

            :param txid: The unvault transaction's txid.
            :param pub1: The first stakeholder pubkey for this vault.
            :param pub2: The second stakeholder pubkey for this vault.
            :param pub3: The third stakeholder pubkey for this vault.
            :param pub4: The fourth stakeholder pubkey for this vault.
            :param address: The address to spend to.
            :param value: The amount to send in sats.
            :param prev_value: The prevout (unvault) value in sats.
            """
            if txid in self.already_signed:
                return jsonify({"sig": None}), 403

            spend_tx = create_spend_tx(lx(txid), 0, value, address)
            pubkeys = [bytes.fromhex(pub) for pub in [pub1, pub2, pub3, pub4]]
            sigs = sign_spend_tx(spend_tx, [self.privkey], pubkeys,
                                 self.pubkey, prev_value)
            return jsonify({"sig": sigs[0].hex()}), 200

        @self.server.route("/getpubkey", methods=["GET"])
        def get_pubkey():
            """Get our pubkey for the vault wallets to form the scripts."""
            return jsonify({"pubkey": self.pubkey.hex()}), 200

    def run(self, host, port, debug):
        self.server.run(host, port, debug)
