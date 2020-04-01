import requests


class CosigningApi:
    """The interaction with the cosigning server."""
    def __init__(self, url):
        """
        :param url: The url of the cosigning server.
        """
        self.url = url

    def get_cosignature(self, txid, pubkeys, addresses, prev_value):
        """Request the cosigning server to sign a spend transaction.

        :param txid: The spend transaction's txid.
        :param pubkeys: A list of the four stakeholders' pubkeys, as bytes.
        :param addresses: A dict of {address: sats}.
        :param prev_value: The amount of the unvault output.

        :return: The signature as bytes.
        """
        r = requests.post("{}/sign".format(self.url), json={
            "txid": txid,
            "pubkeys": [p.hex() for p in pubkeys],
            "addresses": addresses,
            "prev_value": prev_value,
        })
        if r.status_code == 200:
            return bytes.fromhex(r.json()["sig"])
        else:
            raise Exception("Requesting signature for spending {} to cosigning"
                            " server: ({}) {}".format(txid, r.status_code,
                                                      r.text))

    def get_pubkey(self):
        """Request the cosigning server's pubkey.

        :return: The public key, as bytes.
        """
        r = requests.get("{}/getpubkey".format(self.url))
        if r.status_code == 200:
            return bytes.fromhex(r.json()["pubkey"])
        else:
            raise Exception("Requesting cosigning server pubkey: {}"
                            .format(r.text))
