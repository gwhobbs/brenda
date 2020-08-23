from __future__ import print_function
# Brenda -- Blender render tool for Amazon Web Services
# Copyright (C) 2013 James Yonan <james@openvpn.net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import time

import boto

from brenda import aws, utils
from brenda.ami import AMI_ID

def create_instance_with_ebs(opts, conf, new):
    ami_id = utils.get_opt(opts.ami, conf, 'AMI_ID', default=AMI_ID, must_exist=True)
    itype = utils.get_opt(opts.ebs_manage_instance_type, conf, 'EBS_MANAGE_INSTANCE_TYPE', default="t2.micro")
    zone = utils.get_opt(opts.ebs_manage_availability_zone, conf, 'EBS_MANAGE_AVAILABILITY_ZONE')
    ssh_key_name = conf.get("SSH_KEY_NAME", "brenda")
    sec_groups = (conf.get("SECURITY_GROUP", "brenda"),)

    bdm = []
    blkprops = {}
    blkprops['Ebs'] = {}
    if new:
        blkprops['Ebs']['VolumeSize'] = opts.size
    else:
        if opts.size > 1:
            blkprops['Ebs']['VolumeSize'] = opts.size
        if not opts.snapshot:
            raise ValueError("--snapshot must be specified")
        blkprops['Ebs']['SnapshotId'] = aws.translate_snapshot_name(conf, opts.snapshot)

    blkprops['Ebs']['DeleteOnTermination'] = False
    blkprops['DeviceName'] = utils.blkdev(0)
    bdm.append(blkprops)
    istore_block_device = {}
    istore_dev = aws.add_instance_store(opts, conf, istore_block_device, itype)
    bdm.append(istore_block_device)

    script = None
    if opts.mount:
        dev = utils.blkdev(0, mount_form=True)
        script = "#!/bin/bash\n"
        if new:
            script += "/sbin/mkfs -t ext4 %s\n" % (dev,)
        script += "/bin/mount %s /mnt\n" % (dev,)

    run_args = {
        'ImageId'         : ami_id,
        'InstanceType'    : itype,
        'KeyName'         : ssh_key_name,
        'SecurityGroups'  : sec_groups,
        'BlockDeviceMappings' : bdm,
        'MaxCount': 1,
        'MinCount': 1
        }
    if zone:
        run_args['Placement'] = zone
    if script:
        run_args['UserData'] = script

    print("RUN ARGS")
    for k, v in sorted(run_args.items()):
        print("  %s : %r" % (k, v))
    print("BLK DEV PROPS", blkprops)
    print("ISTORE DEV", istore_dev)
    if not opts.dry_run:
        ec2 = aws.get_conn(conf, "ec2")
        reservation = ec2.create_instances(**run_args)
        print(reservation)
