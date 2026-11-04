
import logging
log = logging.getLogger(__name__)

import argparse
import sys
import argcomplete

from thirdparty.izba import Izba


def init_argparse():
    # --- izba
    izba_parser = argparse.ArgumentParser(prog="izba")
    from thirdparty.izba.config import izba_xdg_config_home
    izba_parser.add_argument("--config", dest="config", action="store", help="path to config.yaml", default=izba_xdg_config_home())
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

    # # --- izba inspect [opts] <vm> [<name>]  # dump json about vm profile
    # izba_inspect_parser = izba_subparsers.add_parser("inspect")
    # izba_inspect_parser.add_argument("--name", default="default")
    # izba_inspect_parser.add_argument("profile")
    # izba_inspect_parser.set_defaults(func=izba_inspect_func)

    # --- izba build [opts] <vm> [<name>]    # provision the golden image
    #       [--network=<internet-only|slirp|none>]
    #       [-f] - force recreation
    izba_build_parser = izba_subparsers.add_parser("build")
    izba_build_parser.add_argument("--network", choices=["internet-only", "slirp", "none"], default='none')
    izba_build_parser.add_argument("-f", dest='force', action="store_true", default=False)
    izba_build_parser.add_argument("profile")
    izba_build_parser.set_defaults(func=izba_build_func)

    # --- izba create [opts] <vm> [<name>]  # provision an instance of vm profile
    #       [--network=<internet-only|slirp|none>]
    #       [-f] - force recreation
    izba_create_parser = izba_subparsers.add_parser("create")
    izba_create_parser.add_argument("--network", choices=["internet-only", "slirp", "none"], default='none')
    izba_create_parser.add_argument("--user", default='user')
    izba_create_parser.add_argument("-f", dest='force', action="store_true", default=False)
    izba_create_parser.add_argument("--name", default="default")
    izba_create_parser.add_argument("profile")
    izba_create_parser.set_defaults(func=izba_create_func)

    # --- izba rmi [opts] <vm> [<name>]      # remove vm provisioned golden image
    izba_rmi_parser = izba_subparsers.add_parser("rmi")
    izba_rmi_parser.add_argument("profile")
    izba_rmi_parser.set_defaults(func=izba_rmi_func)

    # --- izba rm [opts] <vm> [<name>]       # remove vm current image
    izba_rm_parser = izba_subparsers.add_parser("rm")
    izba_rm_parser.add_argument("name")
    izba_rm_parser.set_defaults(func=izba_rm_func)

    # --- izba start [opts] <vm> [<name>]    # start vm
    izba_start_parser = izba_subparsers.add_parser("start")
    izba_start_parser.add_argument("name")
    izba_start_parser.set_defaults(func=izba_start_func)

    # --- izba stop [opts] <vm> [<name>]     # kill vm
    izba_stop_parser = izba_subparsers.add_parser("stop")
    izba_stop_parser.add_argument("name")
    izba_stop_parser.set_defaults(func=izba_stop_func)

    # --- izba exec [opts] <vm> [<name>]     # implicitly tty + stdin -> shell
    izba_exec_parser = izba_subparsers.add_parser("exec")
    izba_exec_parser.add_argument("-u", dest='user', default='user')
    izba_exec_parser.add_argument("name")
    izba_exec_parser.set_defaults(func=izba_exec_func)

    # --- izba logs [opts] <vm> [<name>]     # implicitly tty + stdin -> shell
    izba_logs_parser = izba_subparsers.add_parser("logs")
    izba_logs_parser.add_argument("name")
    izba_logs_parser.set_defaults(func=izba_logs_func)

    # --- izba run [opts] <vm> [<name>] -- <args> # run process in vm `izba run -C /path/to/def -- podman build`
    izba_run_parser = izba_subparsers.add_parser("run")
    izba_run_parser.add_argument("-f", dest='force', action="store_true", default=False)
    izba_run_parser.add_argument("-u", dest='user', default='user')
    izba_run_parser.add_argument("--network", choices=["internet-only", "slirp", "none"], default='none')
    izba_run_parser.add_argument("--name", default="default")
    izba_run_parser.add_argument("profile")
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

    # # --- izba load [opts] <vm> [<name>] <path>   # create vm from provided golden image
    # izba_load_parser = izba_subparsers.add_parser("load")
    # izba_load_parser.add_argument("--name", default="default")
    # izba_load_parser.add_argument("profile")
    # izba_load_parser.add_argument("path")
    # izba_load_parser.set_defaults(func=izba_load_func)
    
    # # --- izba save [opts] <vm> [<name>] <path>   # export (copy) vm's golden image
    # izba_save_parser = izba_subparsers.add_parser("save")
    # izba_save_parser.add_argument("--name", default="default")
    # izba_save_parser.add_argument("profile")
    # izba_save_parser.add_argument("path")
    # izba_save_parser.set_defaults(func=izba_save_func)

    return izba_parser


def izba_version_func(args, config):
    from thirdparty.izba import version as izba_version
    return izba_version()


def izba_system_features_func(args, config):
    from thirdparty.izba.system import check_system_features
    check_system_features()


# List profiles and names with instance images.
def izba_ps_func(args, config):
    return Izba(config).ps(all=args.all)


# List profiles and names with golden images.
def izba_images_func(args, config):
    return Izba(config).images()


# def izba_inspect_func(args, config):
#     return Izba(config, profile=args.profile, overlay_name=args.name).inspect()


# Build golden image.
def izba_build_func(args, config):
    Izba(config, profile=args.profile).build()


# Remove golden image.
def izba_rmi_func(args, config):
    Izba(config, profile=args.profile).rmi()


# If instance image missing, call create()
def izba_run_func(args, config):
    Izba(config, profile=args.profile, overlay_name=args.name)\
    .run(network=args.network, user=args.user, command=args.cmd)



# Copy/adjust golden image into instance image (with qemu-img).
# If golden image missing, call build().
def izba_create_func(args, config):
    Izba(config, profile=args.profile, overlay_name=args.name)\
    .create(network=args.network, user=args.user, command=args.cmd)


# Remove instance image (and all overlay images).
# qemu must be shutdown?
def izba_rm_func(args, config):
    Izba(config, overlay_name=args.name).rm()


# If instance image missing, call create()
def izba_start_func(args, config):
    Izba(config, overlay_name=args.name).start()


# Run ssh command in VM
def izba_exec_func(args, config):
    Izba(config, overlay_name=args.name).exec(user=args.user, command=args.cmd)


def izba_logs_func(args, config):
    Izba(config, overlay_name=args.name).logs()


# Kill with pidfile
def izba_stop_func(args, config):
    Izba(config, overlay_name=args.name).stop()





# profile_parts = args.profile.split('/', 1)
# profile_inst = 'default'
# profile_name = None
# if len(profile_parts) > 1:
#     profile_inst = profile_parts[1]

# profile_cls = profile_index._index[profile_name]['class']
# profile_opts = profile_index._index[profile_name]['opts']



# Copy from VM to host:
# - If VM running, we need to snapshot, copy, commit.
# - If VM shutdown we simply dissect.target the file out.
# Copy to VM:
# - If VM running, scp.
# - If VM not running, need read from another VM. libguestfs?
# def izba_cp_func(args, config, profile_cls=None, profile_opts=None, profile_name='default'):
#     return Izba(config, profile=profile_cls(**profile_opts), profile_name=profile_name, overlay_name=args.name)


# # Replace ./profile/name with contents of tar.
# def izba_load_func(args, config, profile_cls=None, profile_opts=None, profile_name='default'):
#     return Izba(config, profile=profile_cls(**profile_opts), profile_name=profile_name, overlay_name=args.name).load()


# # Tar contents of ./profile/name (minus instance) to path.
# def izba_save_func(args, config, profile_cls=None, profile_opts=None, profile_name='default'):
#     return Izba(config, profile=profile_cls(**profile_opts), profile_name=profile_name, overlay_name=args.name).save()





def main():

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

    from thirdparty.izba.config import load_izba_config
    config = load_izba_config(config_path=args.config)
 
    # TODO: translate profile alias to Profile object and pass to func.

    # TODO: The overlay name should be randomly generated if not provided (like docker)

    args.func(args, config)


if __name__ == "__main__":
    main()