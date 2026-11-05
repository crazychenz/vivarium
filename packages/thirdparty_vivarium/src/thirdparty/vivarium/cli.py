#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

import argparse
import sys
import argcomplete


import thirdparty.vivarium.util as vivarium_util
from thirdparty.vivarium.config import (
    load_vivarium_config,
    baseline_empty_config,
    resolve_base_path,
)

from thirdparty.vivarium.rig import Rig


def init_argparse():
    # --- vivarium
    viv_parser = argparse.ArgumentParser(prog="vivarium")
    viv_parser.add_argument("--config", dest="config", action="store", help="path to config.yaml")
    viv_parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity")
    viv_parser.add_argument("--breakpoint", action="store_true", default=False, help="Break before exist on exception.")
    viv_parser.add_argument(
        "--log-level",
        metavar="MODULE:LEVEL",
        action="append",
        default=[],
        help="Example: --log-level thirdparty.vivarium:DEBUG",
    )
    viv_subparsers = viv_parser.add_subparsers(dest="category", required=True)

    viv_version_parser = viv_subparsers.add_parser("version", help="Show version")
    viv_version_parser.set_defaults(func=viv_version_func)

    # --- vivarium config
    viv_config_parser = viv_subparsers.add_parser("config", help="Config management")
    viv_config_subparsers = viv_config_parser.add_subparsers(dest="config_command", required=True)

    # --- vivarium config init
    viv_config_init_parser = viv_config_subparsers.add_parser("init")
    viv_config_init_parser.set_defaults(func=viv_config_init_func)

    # --- viv rig
    viv_rig_parser = viv_subparsers.add_parser("rig", help="Rig management")
    viv_rig_subparsers = viv_rig_parser.add_subparsers(dest="rig_command", required=True)

    # --- viv rig ls
    viv_rig_ls_parser = viv_rig_subparsers.add_parser("ls")
    viv_rig_ls_parser.set_defaults(func=viv_rig_ls_func)

    # --- viv rig build <type>[/name]
    viv_rig_build_parser = viv_rig_subparsers.add_parser("build")
    viv_rig_build_parser.add_argument("rig_profile", default="agent/default")
    viv_rig_build_parser.set_defaults(func=viv_rig_build_func)

    # --- viv rig run <type>[/name]
    viv_rig_run_parser = viv_rig_subparsers.add_parser("run")
    viv_rig_run_parser.add_argument("rig_profile", default="agent/default")
    viv_rig_run_parser.set_defaults(func=viv_rig_run_func)

    # --- viv rig stop <type>[/name]
    viv_rig_stop_parser = viv_rig_subparsers.add_parser("stop")
    viv_rig_stop_parser.add_argument("rig_profile", default="agent/default")
    viv_rig_stop_parser.set_defaults(func=viv_rig_stop_func)

    # --- viv rig rm <type>[/name]
    viv_rig_rm_parser = viv_rig_subparsers.add_parser("rm")
    viv_rig_rm_parser.add_argument("rig_profile", default="agent/default")
    viv_rig_rm_parser.set_defaults(func=viv_rig_rm_func)

    # --- viv rig inspect <type>
    viv_rig_inspect_parser = viv_rig_subparsers.add_parser("inspect")
    viv_rig_inspect_parser.add_argument("rig_name", default="agent/default")
    viv_rig_inspect_parser.set_defaults(func=viv_rig_inspect_func)

    return viv_parser


def version():
    # TODO: This function probably goes somewhere else.
    return [0, 0, 0, 0]


def viv_version_func(args, config):
    log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")
    print('.'.join([str(p) for p in version()]))


def viv_config_init_func(args, config):
    log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

    # TODO: Consider using given config as baseline?
    from thirdparty.vivarium.config import save_vivarium_config
    save_vivarium_config({}, args.config)


def viv_rig_ls_func(args, config):
    log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

    Rig(config).ls()


def viv_rig_build_func(args, config):
    log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

    Rig(config).with_profile(args.rig_profile).build()


def viv_rig_run_func(args, config):
    log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

    Rig(config).with_profile(args.rig_profile).run()


def viv_rig_stop_func(args, config):
    log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

    Rig(config).with_profile(args.rig_profile).stop()


def viv_rig_rm_func(args, config):
    log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

    Rig(config).with_profile(args.rig_profile).rm()


def viv_rig_inspect_func(args, config):
    log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

    Rig(config).with_profile(args.rig_profile).inspect()


def main():
    log.debug(f"--- {sys._getframe().f_code.co_qualname} ---")

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

    base_path = resolve_base_path(config)
 
    # from thirdparty.vivarium.env import apply_env
    # # TODO: Read build tools from config or find newest.
    # apply_env(base_dir)

    try:
        args.func(args, config)
    except Exception as e:
        # TODO: Unlink golden image.
        print(f"Error: {e}")
        if args.verbose > 0:
            import traceback
            traceback.print_exc()
        if args.breakpoint:
            breakpoint()

if __name__ == "__main__":
    main()