#!/usr/bin/env python3

import sys
import logging
log = logging.getLogger(__name__)

import argparse
import argcomplete

from thirdparty.izba import Izba


def init_argparse():
    # --- izba
    izba_parser = argparse.ArgumentParser(prog="izba")
    from thirdparty.izba.config import izba_xdg_config_home
    izba_parser.add_argument("--config", dest="config", action="store", help="path to config.yaml", default=None)
    izba_parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity")
    izba_parser.add_argument("--breakpoint", action="store_true", default=False, help="Break before exist on exception.")
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

    # --- izba import [opts] <distro>       # create a parentless layer from a download
    izba_import_parser = izba_subparsers.add_parser("import")
    izba_import_parser.add_argument("--driver", default='microvm')
    izba_import_parser.add_argument("-t", "--tag", dest='tags', action="append", default=[])
    izba_import_parser.add_argument("--platform-arch", default=None, help="downloads key (default: linux-x64)")
    izba_import_parser.add_argument("--size", default=None, help="root disk size, e.g. 20G")
    izba_import_parser.add_argument("distro")
    izba_import_parser.set_defaults(func=izba_import_func)

    # --- izba build [opts] [-f Izbafile.yaml]  # build a layer (create, provision, commit)
    izba_build_parser = izba_subparsers.add_parser("build")
    izba_build_parser.add_argument("-f", "--file", dest='file', default=None, help="build spec (yaml)")
    izba_build_parser.add_argument("--from", dest='from_', default=None, help="override spec 'from'")
    izba_build_parser.add_argument("--driver", default=None, help="override spec 'driver'")
    izba_build_parser.add_argument("-t", "--tag", "--tags", dest='tags', action="append", default=[])
    izba_build_parser.add_argument("--rm", dest='keep_failed', action="store_false", default=True,
                                   help="remove the container if the build fails")
    izba_build_parser.set_defaults(func=izba_build_func)

    # --- izba commit [opts] <container>     # turn a stopped container into a layer
    izba_commit_parser = izba_subparsers.add_parser("commit")
    izba_commit_parser.add_argument("-t", "--tag", dest='tags', action="append", default=[])
    izba_commit_parser.add_argument("container")
    izba_commit_parser.set_defaults(func=izba_commit_func)

    # --- izba create [opts] <layer>         # create a container from a layer
    izba_create_parser = izba_subparsers.add_parser("create")
    # unused
    izba_run_parser.add_argument("-i", dest='stdin', action="store_true")
    izba_run_parser.add_argument("-t", dest='tty', action="store_true")
    # used
    izba_create_parser.add_argument("--name", dest='name', default=None)
    izba_create_parser.add_argument("--driver", default=None)
    izba_create_parser.add_argument("layer")
    izba_create_parser.set_defaults(func=izba_create_func)

    # --- izba rmi [opts] <layer>            # untag / remove a layer
    izba_rmi_parser = izba_subparsers.add_parser("rmi")
    izba_rmi_parser.add_argument("layer")
    izba_rmi_parser.set_defaults(func=izba_rmi_func)

    # --- izba rm [opts] <container>         # remove a container
    izba_rm_parser = izba_subparsers.add_parser("rm")
    izba_rm_parser.add_argument("-f", dest='force', action="store_true", default=False)
    izba_rm_parser.add_argument("container")
    izba_rm_parser.set_defaults(func=izba_rm_func)

    # --- izba start [opts] <container>
    izba_start_parser = izba_subparsers.add_parser("start")
    izba_start_parser.add_argument("container")
    izba_start_parser.set_defaults(func=izba_start_func)

    # --- izba stop [opts] <container>
    izba_stop_parser = izba_subparsers.add_parser("stop")
    izba_stop_parser.add_argument("container")
    izba_stop_parser.set_defaults(func=izba_stop_func)

    # --- izba exec [opts] <container> [-- command]   # implicitly tty + stdin -> shell
    izba_exec_parser = izba_subparsers.add_parser("exec")
    # unused
    izba_run_parser.add_argument("-i", dest='stdin', action="store_true")
    izba_run_parser.add_argument("-t", dest='tty', action="store_true")
    izba_run_parser.add_argument("-d", dest='tty', action="store_true")
    # used
    izba_exec_parser.add_argument("-u", dest='user', default='user')
    izba_exec_parser.add_argument("container")
    izba_exec_parser.set_defaults(func=izba_exec_func)

    # --- izba logs [opts] <container>
    izba_logs_parser = izba_subparsers.add_parser("logs")
    izba_logs_parser.add_argument("container")
    izba_logs_parser.set_defaults(func=izba_logs_func)

    # --- izba run [opts] <vm> [<name>] -- <args> # run process in vm `izba run -C /path/to/def -- podman build`
    izba_run_parser = izba_subparsers.add_parser("run")
    # unused
    izba_run_parser.add_argument("-i", dest='stdin', action="store_true")
    izba_run_parser.add_argument("-t", dest='tty', action="store_true")
    izba_run_parser.add_argument("-d", dest='tty', action="store_true")
    # used
    izba_run_parser.add_argument("-u", dest='user', default='user')
    izba_run_parser.add_argument("--name", default=None)
    izba_run_parser.add_argument("--rm", dest='remove', action="store_true", default=False,
                                 help="remove the container when the command exits")
    izba_run_parser.add_argument("layer")
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
    return Izba(config).images(all=args.all)


# def izba_inspect_func(args, config):
#     return Izba(config, profile=args.profile, overlay_name=args.name).inspect()


def izba_import_func(args, config):
    source = {"import": args.distro}
    if args.platform_arch:
        source["platform_arch"] = args.platform_arch
    opts = {"size": args.size} if args.size else {}
    Izba(config).import_(source, driver=args.driver, tags=args.tags, **opts)


# Build a layer from a spec file (and/or --from/--driver).
def izba_build_func(args, config):
    spec = {}
    if args.file:
        import yaml
        from pathlib import Path
        spec = yaml.safe_load(Path(args.file).read_text()) or {}
    if args.from_:
        spec["from"] = args.from_
    if args.driver:
        spec["driver"] = args.driver
    Izba(config).build(spec, tags=args.tags, keep_failed=args.keep_failed)


def izba_commit_func(args, config):
    Izba(config).commit(args.container, tags=args.tags)


def izba_rmi_func(args, config):
    Izba(config).rmi(args.layer)


def izba_run_func(args, config):
    from thirdparty.izba.subprocess import stdin_if_noninteractive
    ok = Izba(config).run(args.layer, name=args.name, user=args.user, command=args.cmd,
                          stdin=stdin_if_noninteractive(), remove=args.remove)
    if not ok:
        exit(1)


def izba_create_func(args, config):
    ctr_ctx = Izba(config).create(args.layer, name=args.name, driver=args.driver)
    print(ctr_ctx.id.hex)


def izba_rm_func(args, config):
    Izba(config).rm(args.container, force=args.force)


def izba_start_func(args, config):
    Izba(config).start(args.container)


def izba_exec_func(args, config):
    from thirdparty.izba.subprocess import stdin_if_noninteractive
    ok = Izba(config).exec(args.container, user=args.user, command=args.cmd, stdin=stdin_if_noninteractive())
    if not ok:
        exit(1)


def izba_logs_func(args, config):
    Izba(config).logs(args.container)


def izba_stop_func(args, config):
    Izba(config).stop(args.container)


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

    # dissect logs a traceback for every optional format that isn't installed.
    logging.getLogger("dissect.target").setLevel(logging.ERROR)

    for spec in args.log_level:
        module, level_name = spec.split(":")
        logging.getLogger(module).setLevel(getattr(logging, level_name.upper()))

    from thirdparty.izba.config import load_izba_config
    config = load_izba_config(config_path=args.config)
 
    # TODO: translate profile alias to Profile object and pass to func.

    # TODO: The overlay name should be randomly generated if not provided (like docker)

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
        exit(1)


if __name__ == "__main__":
    main()