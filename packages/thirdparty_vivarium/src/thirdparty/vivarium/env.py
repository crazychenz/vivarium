
import os
import sys


# TODO: Make sure this only runs once per run.
def apply_env(base_dir):

    # TODO: Set any relavant paths.
    os.environ["VIVARIUM_BASE_PATH"] = str(base_dir)

    PATH = [
        #os.path.expandvars("${VIVARIUM_BASE_PATH}/bin"),
    ]

    PATH.append(os.environ["PATH"])
    os.environ["PATH"] = os.path.expandvars(':'.join(PATH))


def print_env(base_dir):

    print(f"export VIVARIUM_BASE_PATH=\"{str(base_dir)}\"")
    print(f"export PATH=\"{os.environ["PATH"]}\"")
    print("# To Apply: (eval \"$(vivarium env print)\" && bash)")


def enter_env(base_dir, cmd):

    # Update environment variables
    env = os.environ.copy()

    # Note: Optionally prevent .bashrc clobbering PS1 by using Add PS1_TAG.
    # TODO: Document this.
    env["PS1_TAG"] = f"({os.path.basename(sys.prefix)}) "

    #DEBUG for v in ["PS1", "VIVARIUM_BASE_PATH"]:
    #DEBUG     print(f"{v}={env[v]}")
    
    #DEBUG print(f"PATH=")
    #DEBUG for p in env['PATH'].split(':'):
    #DEBUG     print(f"  {p}")

    # Replace the current process with bash
    #print(f"Running: {' '.join(cmd)}")
    os.execvpe(cmd[0], cmd, env)