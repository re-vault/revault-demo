import os
import revault
import sys


def show_usage():
    print("usage:")
    print(" python3 {} <bitcoind_conf_path> [host:port]"
          .format(sys.argv[0]))


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        show_usage()
        sys.exit(1)

    conf_path = os.path.abspath(sys.argv[1])
    sigserver = revault.SigServer(bitcoind_conf_path=conf_path)
    host, port = sys.argv[2].split(':') if len(sys.argv) > 2 else (None, None)
    sigserver.run(host=host, port=port, debug=True)
