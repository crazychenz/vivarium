#!/usr/bin/env python3


class Deployment():
    def __init__(self, vivarium_path : Path, name : str = 'default'):
        self.name = name
        self.vivarium_path = vivarium_path
        self.path = self.vivarium_path / "deployments" / name
        # --- generate deployment folder
        # TODO: sanity check and/or sanitize args.deployment_name
        if self.path.exists():
            raise FileExistsError("Deployment {self.name} already exists.")

        self.path.mkdir(parents=True, exist_ok=True)

        # Creates mitm folders, certs, and initial configuration.
        from thirdparty.vivarium.mitmproxy import MitmProxy
        self.mitm = MitmProxy(self)

        # TODO: Create mcpg
        from thirdparty.vivarium.mcpg import McpGateway
        self.mcpg = McpGateway(self)

        # Creates agent vm folders, ssh keys
        from thirdparty.vivarium.agentvm import AgentVm
        self.agent_vm = AgentVm(self)

        # TODO: Creates enclosure vm folders, ssh keys
        from thirdparty.vivarium.enclosurevm import EnclosureVm
        self.enclosure_vm = EnclosureVm(self)

        '''
        - BASE_DIR/cache/downloads/download-name.ext
        - BASE_DIR/cache/downloads/download-name.ext.yaml
          - contains sha256 and whatever else we care about
        - BASE_DIR/deployments/<name>/config.yaml
        - BASE_DIR/deployments/<name>/mitm/default/{config,keys,run,logs,config.yaml}
        - BASE_DIR/deployments/<name>/vm/agent/default/{config,keys,run,logs,config.yaml}
        - BASE_DIR/deployments/<name>/vm/enclosure/default/{config,keys,run,logs,config.yaml}
        - BASE_DIR/deployments/<name>/mcpq/default/{config,keys,run,logs,config.yaml}
        '''
    
    def use_alpine(self, reboot : bool = True):
        from thirdparty.vivarium.agentvm.alpine import AlpineAgentVm
        self.agent_vm.__class__ = AlpineAgentVm
        self.agent_vm.cache_base()
        self.agent_vm.prepare_golden()
        self.agent_vm.prepare_cloud_config(reboot=reboot)
        self.agent_vm.build_import_folder()
        self.agent_vm.build_seed_image()
        self.agent_vm.provision_vm()


