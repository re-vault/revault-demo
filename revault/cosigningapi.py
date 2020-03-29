import requests


class CosigningApi:
    """The interaction with the cosigning server."""
    def __init__(self, url):
        """
        :param url: The url of the cosigning server.
        """
        self.url = url

    def get_signature(self, txid, pubkeys, address, value, prev_value):
        """Request the cosigning server to sign a spend transaction.

        :param tx: The actual spend transaction, as str.
        :param pubkeys: A list of the four stakeholders' pubkeys.

        :return: The signature as bytes.
        """
        r = requests.get("{}/sign/{}/{}/{}/{}/{}"
                         .format(self.url, txid, *pubkeys, address, value,
                                 prev_value))
        if r.status_code == 200:
            return bytes.fromhex(r.json()["sig"])
        else:
            raise Exception("Requesting signature for spending {} to cosigning"
                            " server: {}".format(txid, r.text))

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
