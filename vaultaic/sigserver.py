"""
A dead simple server storing signatures, note that it intentionally doesn't do
any checks or auth.
"""

from flask import Flask, jsonify, request, abort

sigserver = Flask(__name__)

# The dict storing the ordered (hex) signatures, like:
# signatures["txid"] = [sig_stk1, sig_stk2, sig_stk3, sig_stk4]
signatures = {}


@sigserver.route("/sig/<string:txid>/<int:stk_id>", methods=["POST", "GET"])
def get_post_signatures(txid, stk_id):
    """Get or give a signature for {txid}, by the {stk_id}th stakeholder."""
    if request.method == "POST":
        if txid not in signatures.keys():
            signatures[txid] = [None] * 4
        sig = request.form.get("sig", None)
        signatures[txid][stk_id - 1] = sig
        return jsonify({"sig": sig}), 201
    elif request.method == "GET":
        if txid not in signatures:
            abort(404)
        sig = signatures[txid][stk_id - 1]
        if sig is None:
            abort(404)
        return jsonify({"sig": sig}), 200
