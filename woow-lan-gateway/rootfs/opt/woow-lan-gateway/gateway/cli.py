import logging
import sys

from .app import GatewayApplication, cleanup


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "run":
        return GatewayApplication().run()
    if command == "cleanup":
        return cleanup()
    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
