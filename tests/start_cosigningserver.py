import revault
import sys


def show_usage():
    print("usage:")
    print(" python3 {} [host:port]".format(sys.argv[0]))


if __name__ == "__main__":
    if len(sys.argv) not in (1, 2):
        show_usage()
        sys.exit(1)

    sigserver = revault.CosigningServer()
    host, port = sys.argv[1].split('//')[-1].split(':') if len(sys.argv) > 1 else (None, None)
    sigserver.run(host=host, port=port, debug=True)
