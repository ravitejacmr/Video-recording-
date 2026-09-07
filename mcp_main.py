import sys

if __name__ == '__main__':
    if '--connect' in sys.argv:
        from studio.tunnel_setup import main
    else:
        from studio.mcp_server import main
    raise SystemExit(main())
