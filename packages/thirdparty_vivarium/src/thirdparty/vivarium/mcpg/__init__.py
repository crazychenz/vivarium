#!/usr/bin/env python3

class McpGateway():
    # *Note: Do not store deployment ref in class, we do not want 
    # *bi-directional linkage between vivarium these classes.
    def __init__(self, deployment : "Deployment", name: str = 'default'):
        self.deployment_path = deployment.path
        self.path = self.deployment_path / 'mcpg' / name
        # keys for ssh keys and certs
        # run for sockets and pid files
        for sub in ['config', 'keys', 'run', 'logs']:
            (self.path / sub).mkdir(parents=True, exist_ok=True)