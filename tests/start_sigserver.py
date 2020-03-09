from utils import SIGSERV_URL
from vaultaic import SigServer

host, port = SIGSERV_URL.split(':') if SIGSERV_URL else (None, None)
sigserver = SigServer()
sigserver.run(host=host, port=port, debug=True)
