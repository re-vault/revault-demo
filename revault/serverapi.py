import requests

from bitcoin.core import COIN
from decimal import Decimal


class ServerApi:
    """The interaction with the signature server.

    Still called sigserver, but we'll use it for a number of things.
    """
    def __init__(self, url):
        """
        :param url: The url of the sigserver.
        """
        self.url = url

    def send_signature(self, txid, sig, stk_id):
        """Send a signature to the server.

        :param sig: The signature as bytes or str
        :param txid: The id of the transaction this transaction is for
        :param stk_id: The id of the stakeholder this transaction is from
        """
        if isinstance(sig, bytes):
            sig = sig.hex()
        elif not isinstance(sig, str):
            raise Exception("The signature must be either bytes or a valid hex"
                            " string")
        r = requests.post("{}/sig/{}/{}".format(self.url, txid, stk_id),
                          data={"sig": sig})
        if not r.status_code == 201:
            raise Exception("stakeholder #{}: Could not send sig '{}' for"
                            " txid {}.".format(stk_id, sig, txid))

    def get_signature(self, txid, stk_id):
        """Request a signature to the signature server.

        :param txid: The txid of the transaction we're interested in.
        :param stk_id: The id of the stakeholder this signature was from.

        :return: The signature as bytes, or None if not found.
        """
        r = requests.get("{}/sig/{}/{}".format(self.url, txid, stk_id))
        if r.status_code == 200:
            return bytes.fromhex(r.json()["sig"])
        elif r.status_code == 404:
            return None
        else:
            raise Exception("Requesting stakeholder #{}'s signature for tx "
                            "{}, response {}".format(stk_id, txid, r.text))

    def get_emergency_feerate(self, txid):
        """Get the feerate for the emergency transaction.

        :param txid: The emergency transaction id, as str.
        :return: The feerate in **sat/VByte**, as int.
        """
        r = requests.get("{}/emergency_feerate/{}".format(self.url, txid))
        if not r.status_code == 200:
            raise Exception("The sigserver returned with '{}', saying '{}'"
                            .format(r.status_code, r.text))
        btc_perkvb = Decimal(r.json()["feerate"])
        # Explicit conversion to sat per virtual byte
        return int(btc_perkvb * Decimal(COIN) / Decimal(1000))
