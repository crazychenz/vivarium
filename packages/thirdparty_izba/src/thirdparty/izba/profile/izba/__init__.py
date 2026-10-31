
from thirdparty.izba.cli.registrar import ProfileIndex


class IzbaCrtProfile():
    pass


def register_profile_crt(profile_index: ProfileIndex):
    profile_index.register_profile_class('crt', IzbaCrtProfile)

