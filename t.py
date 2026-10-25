#!/usr/bin/env python3
import yaml

def build_cloud_config():
    import thirdparty.qemu.cloud_init.lib as cc
    user_data = cc.CloudConfig(
        disable_root=False,
        ssh_pwauth=True,
        users=[
            cc.Users(
                name="agent",
                shell="/bin/sh",
                lock_passwd=False,
                #ssh_authorized_keys=open('path/to/pub_key').read()
                passwd='gofish',
            ),
            cc.Users(
                name="root",
                shell="/bin/sh",
                lock_passwd=False,
                #ssh_authorized_keys=open('path/to/pub_key').read()
                passwd='gofish',
            ),
        ],
        write_files=[
            cc.WriteFile(
                path="/etc/ssh/sshd_config.d/10-hardening.conf",
                content="PasswordAuthentication no\\nPermitRootLogin no\\nAllowAgentForwarding no",
            ),
        ],
        package_update=True,
        packages=['docker', 'docker-cli-buildx'],
        runcmd=[
            # SSH Things and Stuff
            "printf '%s\\n' 'PasswordAuthentication no' 'PermitRootLogin no' 'AllowAgentForwarding no' | cat - /etc/ssh/sshd_config > /tmp/sshd_config.new",
            "cat /tmp/sshd_config.new > /etc/ssh/sshd_config",
            "rm -f /tmp/sshd_config.new",
            "rc-service sshd restart",
            # Everything Else
            "mkdir -p /mnt/seed /opt/agent-image",
            [ 'sh', '-c', r"mount -o ro $(findfs LABEL=cidata) /mnt/seed" ],
            "cp -r /mnt/seed/agent-image/. /opt/agent-image/",
            "cp /mnt/seed/mitmproxy.crt /usr/local/share/ca-certificates/mitmproxy.crt",
            "update-ca-certificates",
            "umount /mnt/seed",
            "addgroup agent docker",
            "rc-update add docker default",
            "rc-service docker start",
            "#docker build -t agent:latest /opt/agent-image",
            "addgroup agent wheel",
            "echo 'permit nopass :wheel' > /etc/doas.d/doas.conf",
        ],
        power_state=cc.PowerState(
            mode=cc.Mode3.reboot,
            message='provisioned',
            timeout=30,
            condition=True
        ),
    )
    return user_data


from thirdparty.qemu.cloud_init import to_yaml

user_data = build_cloud_config()
#user_data_yaml = yaml.safe_dump(user_data.model_dump(exclude_none=True, by_alias=True))
user_data_yaml = to_yaml(user_data)
print(user_data_yaml)

