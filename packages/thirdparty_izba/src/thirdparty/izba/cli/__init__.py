
import logging
log = logging.getLogger(__name__)

import argparse
import sys
import argcomplete

from thirdparty.izba import Izba


def init_argparse():
    # --- izba
    izba_parser = argparse.ArgumentParser(prog="izba")
    izba_parser.add_argument("--config", dest="config", action="store", help="path to config.yaml")
    izba_parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity")
    izba_parser.add_argument(
        "--log-level",
        metavar="MODULE:LEVEL",
        action="append",
        default=[],
        help="Example: --log-level thirdparty.izba:DEBUG",
    )
    izba_subparsers = izba_parser.add_subparsers(dest="subcommand", required=True)

    # --- izba version                       # display version of izba
    izba_version_parser = izba_subparsers.add_parser("version")
    izba_version_parser.set_defaults(func=izba_version_func)

    # --- izba system
    izba_system_parser = izba_subparsers.add_parser("system", help="Inspect the host system")
    izba_system_subparsers = izba_system_parser.add_subparsers(dest="izba_system_command", required=True)

    # --- izba system features
    izba_system_features_parser = izba_system_subparsers.add_parser("features")
    izba_system_features_parser.set_defaults(func=izba_system_features_func)

    # --- izba ps [opts] [-a]                # print running izba vm profile states, -a for all profile states
    izba_ps_parser = izba_subparsers.add_parser("ps")
    izba_ps_parser.add_argument("-a", dest='all', action="store_true", default=False)
    izba_ps_parser.set_defaults(func=izba_ps_func)

    # --- izba images [opts] [-a]            # print built golden images, -a for all profile images
    izba_images_parser = izba_subparsers.add_parser("images")
    izba_images_parser.add_argument("-a", dest='all', action="store_true", default=False)
    izba_images_parser.set_defaults(func=izba_images_func)

    # --- izba inspect [opts] <vm> [<name>]  # dump json about vm profile
    izba_inspect_parser = izba_subparsers.add_parser("inspect")
    izba_inspect_parser.add_argument("profile")
    izba_inspect_parser.add_argument("name", nargs="?", default="default")
    izba_inspect_parser.set_defaults(func=izba_inspect_func)

    # --- izba build [opts] <vm> [<name>]    # provision the golden image
    #       [--network=<internet-only|slirp|none>]
    #       [-f] - force recreation
    izba_build_parser = izba_subparsers.add_parser("build")
    izba_build_parser.add_argument("--network", choices=["internet-only", "slirp", "none"], default='none')
    izba_build_parser.add_argument("-f", dest='force', action="store_true", default=False)
    izba_build_parser.add_argument("profile")
    izba_build_parser.add_argument("name", nargs="?", default="default")
    izba_build_parser.set_defaults(func=izba_build_func)

    # --- izba create [opts] <vm> [<name>]  # provision an instance of vm profile
    #       [--network=<internet-only|slirp|none>]
    #       [-f] - force recreation
    izba_create_parser = izba_subparsers.add_parser("create")
    izba_create_parser.add_argument("--network", choices=["internet-only", "slirp", "none"], default='none')
    izba_create_parser.add_argument("-f", dest='force', action="store_true", default=False)
    izba_create_parser.add_argument("profile")
    izba_create_parser.add_argument("name", nargs="?", default="default")
    izba_create_parser.set_defaults(func=izba_create_func)

    # --- izba rmi [opts] <vm> [<name>]      # remove vm provisioned golden image
    izba_rmi_parser = izba_subparsers.add_parser("rmi")
    izba_rmi_parser.add_argument("profile")
    izba_rmi_parser.add_argument("name", nargs="?", default="default")
    izba_rmi_parser.set_defaults(func=izba_rmi_func)

    # --- izba rm [opts] <vm> [<name>]       # remove vm current image
    izba_rm_parser = izba_subparsers.add_parser("rm")
    izba_rm_parser.add_argument("profile")
    izba_rm_parser.add_argument("name", nargs="?", default="default")
    izba_rm_parser.set_defaults(func=izba_rm_func)

    # --- izba start [opts] <vm> [<name>]    # start vm
    izba_start_parser = izba_subparsers.add_parser("start")
    izba_start_parser.add_argument("--network", choices=["internet-only", "slirp", "none"], default='none')
    izba_start_parser.add_argument("-f", dest='force', action="store_true", default=False)
    izba_start_parser.add_argument("profile")
    izba_start_parser.add_argument("name", nargs="?", default="default")
    izba_start_parser.set_defaults(func=izba_start_func)

    # --- izba stop [opts] <vm> [<name>]     # kill vm
    izba_stop_parser = izba_subparsers.add_parser("stop")
    izba_stop_parser.add_argument("profile")
    izba_stop_parser.add_argument("name", nargs="?", default="default")
    izba_stop_parser.set_defaults(func=izba_stop_func)

    # --- izba exec [opts] <vm> [<name>]     # implicitly tty + stdin -> shell
    izba_exec_parser = izba_subparsers.add_parser("exec")
    izba_exec_parser.add_argument("profile")
    izba_exec_parser.add_argument("name", nargs="?", default="default")
    izba_exec_parser.set_defaults(func=izba_exec_func)

    # --- izba run [opts] <vm> [<name>] -- <args> # run process in vm `izba run -C /path/to/def -- podman build`
    izba_run_parser = izba_subparsers.add_parser("run")
    izba_run_parser.add_argument("--network", choices=["internet-only", "slirp", "none"], default='none')
    izba_run_parser.add_argument("-f", dest='force', action="store_true", default=False)
    izba_run_parser.add_argument("profile")
    izba_run_parser.add_argument("name", nargs="?", default="default")
    izba_run_parser.set_defaults(func=izba_run_func)
    izba_run_parser.usage = (
        izba_run_parser.format_usage()
        .replace("usage: ", "", 1)
        .rstrip()
        .replace("%", "%%")
        + " [ -- command [args ...] ]"
    )
    

    # # --- izba cp [opts] <vm> <name>:<src> <dst>  # copy data to microvm ... can we use 9p?
    # # --- izba cp [opts] <vm> <src> <name>:<dst>  # copy data from microvm ... can we use 9p?
    # izba_cp_parser = izba_subparsers.add_parser("cp")
    # izba_cp_parser.set_defaults(func=izba_cp_func)

    # --- izba load [opts] <vm> [<name>] <path>   # create vm from provided golden image
    izba_load_parser = izba_subparsers.add_parser("load")
    izba_load_parser.add_argument("profile")
    izba_load_parser.add_argument("name", nargs="?", default="default")
    izba_load_parser.add_argument("path")
    izba_load_parser.set_defaults(func=izba_load_func)
    
    # --- izba save [opts] <vm> [<name>] <path>   # export (copy) vm's golden image
    izba_save_parser = izba_subparsers.add_parser("save")
    izba_save_parser.add_argument("profile")
    izba_save_parser.add_argument("name", nargs="?", default="default")
    izba_save_parser.add_argument("path")
    izba_save_parser.set_defaults(func=izba_save_func)

    return izba_parser


def izba_version_func(args, config):
    return Izba(config).version()


def izba_system_features_func(args, config):
    from thirdparty.izba.system import check_system_features
    check_system_features()


# List profiles and names with instance images.
def izba_ps_func(args, config):
    return Izba(config).ps()


# List profiles and names with golden images.
def izba_images_func(args, config):
    return Izba(config).images()


def izba_inspect_func(args, config, profile_cls=None, profile_opts=None):
    return Izba(config).inspect()


# Build golden image.
def izba_build_func(args, config, profile_cls=None, profile_opts=None):
    return Izba(config).build()


# Copy/adjust golden image into instance image (with qemu-img).
# If golden image missing, call build().
def izba_create_func(args, config, profile_cls=None, profile_opts=None):
    return Izba(config).create()


# Remove golden image.
def izba_rmi_func(args, config, profile_cls=None, profile_opts=None):
    return Izba(config).rmi()


# Remove instance image (and all overlay images).
# qemu must be shutdown?
def izba_rm_func(args, config, profile_cls=None, profile_opts=None):
    return Izba(config).rm()


# If instance image missing, call create()
def izba_start_func(args, config, profile_cls=None, profile_opts=None):
    return Izba(config).start()


# Kill with pidfile
def izba_stop_func(args, config, profile_cls=None, profile_opts=None):
    return Izba(config).stop()


# Run ssh command in VM
def izba_exec_func(args, config, profile_cls=None, profile_opts=None):
    return Izba(config).exec()


# If instance image missing, call create()
def izba_run_func(args, config, profile_cls=None, profile_opts=None):
    return Izba(config).run()


# Copy from VM to host:
# - If VM running, we need to snapshot, copy, commit.
# - If VM shutdown we simply dissect.target the file out.
# Copy to VM:
# - If VM running, scp.
# - If VM not running, need read from another VM. libguestfs?
# def izba_cp_func(args, config, profile_cls=None, profile_opts=None):
#     return Izba(config).


# Replace ./profile/name with contents of tar.
def izba_load_func(args, config, profile_cls=None, profile_opts=None):
    return Izba(config).load()


# Tar contents of ./profile/name (minus instance) to path.
def izba_save_func(args, config, profile_cls=None, profile_opts=None):
    return Izba(config).save()


def main():

    from thirdparty.izba.cli.registrar import get_izba_profile_eps

    profile_index = get_izba_profile_eps()

    izba_parser = init_argparse()
    argcomplete.autocomplete(izba_parser)

    # Only applicable for "izba run", but req'd to do it here.
    argv = sys.argv[1:]
    cmd = None
    if "--" in argv:
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1:]

    args = izba_parser.parse_args(argv)
    args.cmd = cmd

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

    config = {}

    import thirdparty.izba.config as cfg
    # Default config
    config = cfg.baseline_empty_config()
    # Default config path
    config_path = cfg.xdg_config_home() / "izba" / "config.yaml"
    if args.config:
        config_path = Path(args.config)
    if config_path.exists():
        config = cfg.load_izba_config(config_path=config_path)
    else:
        print(f"Config not found at: {config_path}, using defaults.")
 
    # TODO: translate profile alias to Profile object and pass to func.

    if hasattr(args, 'profile'):
        profile_cls = profile_index._index[args.profile]['class']
        profile_opts = profile_index._index[args.profile]['opts']

        args.func(args, config, profile_cls=profile_cls, profile_opts=profile_opts)
    else:
        args.func(args, config)


if __name__ == "__main__":
    main()