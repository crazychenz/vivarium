

from thirdparty.vivarium.config import save_vivarium_config

class VivariumConfig:
    @staticmethod
    def register_with_subparser(subparser):
        # --- vivarium config
        vivarium_config_parser = subparser.add_parser("config", help="Config management")
        vivarium_config_subparsers = vivarium_config_parser.add_subparsers(dest="config_command", required=True)

        # --- vivarium config init
        vivarium_config_init_parser = vivarium_config_subparsers.add_parser("init")
        vivarium_config_init_parser.set_defaults(func=VivariumConfig.init_func)


    @staticmethod
    def init_func(args, config):
        # TODO: Consider using given config as baseline?
        save_vivarium_config({}, args.config)