import os

from bitcoin.wallet import CKey
from bitcoin.core import b2x
from flask import Flask, jsonify

from .transactions import sign_spend_tx


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
        self.setup_routes()

    def setup_routes(self):
        @self.server.route("/sign/<string:tx>/<string:pub1>/<string:pub2>/"
                           "<string:pub3>/<string:pub4>", methods=["GET"])
        def get_signature(tx, pub1, pub2, pub3, pub4):
            """Sign a spend transaction. Ugly API because P2(W)SH.

            :param tx: The actual spend transaction.
            :param pub1: The first stakeholder pubkey.
            :param pub2: The second stakeholder pubkey.
            :param pub3: The third stakeholder pubkey.
            :param pub4: The fourth stakeholder pubkey.
            """
            # Some sanity checks
            if b2x(tx.GetTxid()) in self.already_signed \
                    or len(tx.vin) != 1 or len(tx.vin[0].scriptSig) != 0:
                return jsonify({"sig": None}), 403

            sigs = sign_spend_tx(tx, [self.privkey], [pub1, pub2, pub3, pub4],
                                 self.pubkey)
            return jsonify({"sig": sigs[0]}), 200

        @self.server.route("/getpubkey", methods=["GET"])
        def get_pubkey():
            """Get our pubkey for the vault wallets to form the scripts."""
            return jsonify({"pubkey": CKey(self.pubkey).pub.hex()})

    def run(self, host, port, debug):
        self.server.run(host, port, debug)
