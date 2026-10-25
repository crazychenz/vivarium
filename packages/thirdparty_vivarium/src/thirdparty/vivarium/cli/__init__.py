
import logging
log = logging.getLogger(__name__)

import argparse
import sys
import argcomplete


import thirdparty.vivarium.util as vivarium_util
from thirdparty.vivarium.config import (
    load_vivarium_config,
    baseline_empty_config,
    resolve_base_dir,
)


from .deployment_cli import VivariumDeployment
from .config_cli import VivariumConfig


def init_argparse():
    # --- vivarium
    vivarium_parser = argparse.ArgumentParser(prog="vivarium")
    vivarium_parser.add_argument("--config", dest="config", action="store", help="path to config.yaml")
    vivarium_parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity")
    vivarium_parser.add_argument(
        "--log-level",
        metavar="MODULE:LEVEL",
        action="append",
        default=[],
        help="Example: --log-level thirdparty.vivarium:DEBUG",
    )
    vivarium_subparsers = vivarium_parser.add_subparsers(dest="category", required=True)

    VivariumConfig.register_with_subparser(vivarium_subparsers)
    VivariumDeployment.register_with_subparser(vivarium_subparsers)

    return vivarium_parser


def main():
    vivarium_parser = init_argparse()
    argcomplete.autocomplete(vivarium_parser)
    args = vivarium_parser.parse_args()

    level = {
        0: logging.ERROR,
        1: logging.WARNING,
        2: logging.INFO,
        3: logging.DEBUG,
    }.get(args.verbose, logging.DEBUG)

    logging.basicConfig(level=level, format="%(levelname)-8s %(name)s: %(message)s")

    for spec in args.log_level:
        module, level_name = spec.split(":")
        logging.getLogger(module).setLevel(getattr(logging, level_name.upper()))

    # Default config
    config = baseline_empty_config()
    # Default config path
    config_path = vivarium_util.xdg_config_home() / "vivarium" / "config.yaml"
    if args.config:
        config_path = Path(args.config)
    if config_path.exists():
        config = load_vivarium_config(config_path=config_path)
    else:
        print(f"Config not found at: {config_path}, using defaults.")

    base_dir = resolve_base_dir(config)
 
    # from thirdparty.vivarium.env import apply_env
    # # TODO: Read build tools from config or find newest.
    # apply_env(base_dir)

    args.func(args, config)


if __name__ == "__main__":
    main()