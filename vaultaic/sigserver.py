import bitcoin.rpc

from flask import Flask, jsonify, request, abort
from decimal import Decimal


class SigServer:
    """
    A wrapper around a dead simple server storing signatures and providing
    feerates, note that it intentionally doesn't do any checks or auth.
    """
    def __init__(self, bitcoind_conf_path):
        """Uncommon pattern, but a handy one. We setup everything when the
        wrapper is initialized."""
        self.server = Flask(__name__)
        # The dict storing the ordered (hex) signatures, like:
        # signatures["txid"] = [sig_stk1, sig_stk2, sig_stk3, sig_stk4]
        self.signatures = {}
        # We need to talk to bitcoind to gather feerates
        self.bitcoind_conf_path = bitcoind_conf_path
        self.bitcoind = bitcoin.rpc.RawProxy(btc_conf_file=bitcoind_conf_path)
        # We need to give the same feerate to all the wallets, so we keep track
        # of the feerate we already gave by txid
        self.feerates = {}
        self.setup_routes()

    def setup_routes(self):
        @self.server.route("/sig/<string:txid>/<int:stk_id>",
                           methods=["POST", "GET"])
        def get_post_signatures(txid, stk_id):
            """Get or give a signature for {txid}, by the {stk_id}th
            stakeholder."""
            if request.method == "POST":
                if txid not in self.signatures.keys():
                    self.signatures[txid] = [None] * 4
                sig = request.form.get("sig", None)
                self.signatures[txid][stk_id - 1] = sig
                return jsonify({"sig": sig}), 201
            elif request.method == "GET":
                if txid not in self.signatures:
                    abort(404)
                sig = self.signatures[txid][stk_id - 1]
                if sig is None:
                    abort(404)
                return jsonify({"sig": sig}), 200

        @self.server.route("/emergency_feerate/<string:txid>",
                           methods=["POST", "GET"])
        def get_emergency_feerate(txid):
            """Get the feerate for an emergency transaction.

            This returns fucking virtual bytes, hopefully we have a large
            enough room with a 10* estimate.
            """
            if txid not in self.feerates.keys():
                # We use 10* the conservative estimation at 1 block for such a
                # crucial transaction
                feerate = self.bitcoind.estimatesmartfee(1, "CONSERVATIVE")
                self.feerates[txid] = feerate["feerate"] * Decimal(10)
            return jsonify({"feerate": float(self.feerates[txid])})

    def test_client(self):
        return self.server.test_client()

    def run(self, host, port, debug):
        self.server.run(host, port, debug)
