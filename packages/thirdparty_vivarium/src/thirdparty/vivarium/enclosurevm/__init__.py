#!/usr/bin/env python3

class EnclosureVm():
    # *Note: Do not store deployment ref in class, we do not want 
    # *bi-directional linkage between vivarium these classes.
    def __init__(self, deployment : "Deployment", name: str = 'default'):
        self.deployment_path = deployment.path
        self.path = self.deployment_path / 'vm' / 'enclosure' / name
        # keys for ssh keys and certs
        # run for sockets and pid files
        # import for staging seed
        for sub in ['config', 'keys', 'run', 'logs', 'import']:
            (self.path / sub).mkdir(parents=True, exist_ok=True)
        
        from thirdparty.vivarium.util import generate_ssh_keys
        generate_ssh_keys(self.path / "keys", "user@enclosure")