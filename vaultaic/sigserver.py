from flask import Flask, jsonify, request, abort


class SigServer:
    """
    A wrapper around a dead simple server storing signatures and providing
    feerates, note that it intentionally doesn't do any checks or auth.
    """
    def __init__(self):
        """Uncommon pattern, but a handy one. We setup everything when the
        wrapper is initialized."""
        self.server = Flask(__name__)
        # The dict storing the ordered (hex) signatures, like:
        # signatures["txid"] = [sig_stk1, sig_stk2, sig_stk3, sig_stk4]
        self.signatures = {}
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

    def test_client(self):
        return self.server.test_client()

    def run(self, host, port, debug):
        self.server.run(host, port, debug)
