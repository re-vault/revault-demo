from utils import SIGSERV_URL
from vaultaic import sigserver

host, port = SIGSERV_URL.split(':') if SIGSERV_URL else (None, None)
sigserver.run(host=host, port=port, debug=True)
