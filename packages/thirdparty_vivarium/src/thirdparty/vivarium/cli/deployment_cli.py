#!/usr/bin/env python3


class VivariumDeployment:
    @staticmethod
    def register_with_subparser(subparser):
        # --- vivarium deployment
        vivarium_deployment_parser = subparser.add_parser("deployment", help="Deployment management")
        vivarium_deployment_subparsers = vivarium_deployment_parser.add_subparsers(dest="deployment_command", required=True)

        # --- vivarium deployment ls
        vivarium_deployment_ls_parser = vivarium_deployment_subparsers.add_parser("ls")
        vivarium_deployment_ls_parser.set_defaults(func=VivariumDeployment.deployment_ls_func)

        # --- vivarium deployment init <name>
        vivarium_deployment_init_parser = vivarium_deployment_subparsers.add_parser("init")
        vivarium_deployment_init_parser.add_argument("--no-reboot", dest='reboot', action="store_false", default=True)
        vivarium_deployment_init_parser.add_argument("deployment_name", nargs="?", default="default")
        vivarium_deployment_init_parser.set_defaults(func=VivariumDeployment.deployment_init_func)

        # TODO: start and stop for deployment
        # TODO: --now for init to start when complete

        # --- vivarium deployment rm <name>
        vivarium_deployment_rm_parser = vivarium_deployment_subparsers.add_parser("rm")
        vivarium_deployment_rm_parser.add_argument("-f", "--force", dest="force", action="store_true", default=False)
        vivarium_deployment_rm_parser.add_argument("deployment_name")
        vivarium_deployment_rm_parser.set_defaults(func=VivariumDeployment.deployment_rm_func)

        # --- vivarium deployment info <name>
        vivarium_deployment_info_parser = vivarium_deployment_subparsers.add_parser("info")
        vivarium_deployment_info_parser.add_argument("deployment_name", nargs="?", default="default")
        vivarium_deployment_info_parser.set_defaults(func=VivariumDeployment.deployment_info_func)


    @staticmethod
    def deployment_ls_func(args, config):
        from pathlib import Path
        from thirdparty.vivarium.config import resolve_base_dir
        base_dir = resolve_base_dir(config)

        p = Path(base_dir / "deployments")
        names = [d.name for d in p.iterdir() if d.is_dir()]
        for name in names:
            print(name)


    @staticmethod
    def deployment_init_func(args, config):
        from thirdparty.vivarium.config import resolve_base_dir
        vivarium_base_dir = resolve_base_dir(config)

        # Creates folder structure
        from thirdparty.vivarium.deployment import Deployment
        deployment = Deployment(vivarium_base_dir, name=args.deployment_name)
        deployment.use_alpine(reboot=args.reboot)

        # TODO: Consider releasing a build of qemu-wg-bridge upstream for easy caching.


    @staticmethod
    def deployment_rm_func(args, config):
        from thirdparty.vivarium.config import resolve_base_dir
        import shutil
        base_dir = resolve_base_dir(config)
        deployments_dir = base_dir / "deployments"

        target = (deployments_dir / args.deployment_name).resolve()
        base = base_dir.resolve()

        # safety: must be a real directory strictly inside base_dir
        if target == base or base not in target.parents:
            raise ValueError(f"refusing to remove {target}: not inside {base}")
        if not target.is_dir() or target.is_symlink():
            print(f"{target} is not a directory")
            exit(1) #return False
        
        if not args.force:
            if input(f"Delete {target} and everything in it? [y/N] ").strip().lower() != "y":
                print("aborted")
                exit(0) #return False
        
        shutil.rmtree(target)
        print(f"removed {args.deployment_name}")
        #return True


    @staticmethod
    def deployment_info_func(args, config):
        # Extract everything.
        from thirdparty.vivarium.config import resolve__dir, resolve_base_dir
        base_dir = resolve_base_dir(config)

        print("vivarium deployment info not implemented")
        print(f"name = {args.deployment_name}")
        print(f"base_dir = {base_dir}")



