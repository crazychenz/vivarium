#!/usr/bin/env python3

class BaseProfile():


    @staticmethod
    def type_name():
        raise NotImplementedError()


    def get_type_name(self):
        return type(self).type_name()


    # Prepare all guest data that is not cloud_config (user-data) or meta-data
    # - scripts
    # - dockerfiles, containerfiles, manifests, binaries, configurations
    # Depends on: generate_ssh_keys()
    def prepare_golden_guest_data(self):
        raise NotImplementedError()

    def prepare_instance_guest_data(self):
        raise NotImplementedError()


    # Build cloud config representative of the profile's use case.
    # Depends on: prepare_guest_data()
    def prepare_golden_cloud_config(self, reboot : bool = True):
        raise NotImplementedError()

    def prepare_instance_cloud_config(self, reboot : bool = True):
        raise NotImplementedError()


    # When the cloud_config (ie user-data) is delivered to the VM,
    # everything in the import folder will also be delivered.
    # Note: user ssh keys already included in seed
    # Depends on: prepare_guest_data()
    def build_golden_context_folder(self):
        raise NotImplementedError()
    
    def build_instance_context_folder(self):
        raise NotImplementedError()


    # Construct the seed image itself:
    # - user-data
    # - meta-data
    # - keys/
    # - import/
    # Depends on: prepare_cloud_config(), build_import_folder()
    def build_golden_seed_image(self):
        raise NotImplementedError()
    
    def build_instance_seed_image(self):
        raise NotImplementedError()


    # Download the base image we'll base golden and instance images from.
    # Depends on cached target, internet, or available mirror.
    def cache_base(self, url=None, fname=None):
        raise NotImplementedError()


    # Copy/adjust the base to the golden (before running golden first-boot)
    # Depends on: cache_base
    def prepare_golden_disk_image(self):
        raise NotImplementedError()


    # Runs the VM and shuts down when complete.
    # Depends on: prepare_golden(), build_seed_image()
    def build_golden_disk_image(self):
        raise NotImplementedError()


    # Copy/adjust the golden to the instance
    # Depends on: build_golden(self)
    def prepare_instance_disk_image(self):
        raise NotImplementedError()


    # Starts the VM and leaves running until kill or stop.
    def start_instance_vm(self, **opts):
        raise NotImplementedError()


    # Stops the VM.
    def stop_instance_vm(self):
        raise NotImplementedError()


    # Executes command in VM (via SSH)
    def exec_instance_vm(self):
        raise NotImplementedError()


    # Starts VM, runs a single script, shuts down VM.
    def run_instance_vm(self):
        raise NotImplementedError()