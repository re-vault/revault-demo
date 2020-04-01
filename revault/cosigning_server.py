import bitcoin
import os

from bitcoin.core import lx
from bitcoin.wallet import CKey
from flask import Flask, jsonify, request

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
        @self.server.route("/sign", methods=["POST"])
        def get_signature():
            """Sign a spend transaction."""
            params = request.get_json()
            # Crash if it doesn't contain all entries !
            txid = params["txid"]
            if txid in self.already_signed:
                return jsonify({"sig": None}), 403
            pubkeys = params["pubkeys"]
            addresses = params["addresses"]
            prev_value = params["prev_value"]

            spend_tx = create_spend_tx(lx(txid), 0, addresses)
            pubkeys = [bytes.fromhex(pub) for pub in pubkeys]
            sigs = sign_spend_tx(spend_tx, [self.privkey], pubkeys,
                                 self.pubkey, prev_value)
            return jsonify({"sig": sigs[0].hex()}), 200

        @self.server.route("/getpubkey", methods=["GET"])
        def get_pubkey():
            """Get our pubkey for the vault wallets to form the scripts."""
            return jsonify({"pubkey": self.pubkey.hex()}), 200

    def run(self, host, port, debug):
        self.server.run(host, port, debug)
