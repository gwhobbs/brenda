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

import os, time
from brenda import aws, utils
from brenda.ami import AMI_ID
import base64

def demand(opts, conf):
    ami_id = utils.get_opt(opts.ami, conf, 'AMI_ID', default=AMI_ID, must_exist=True)
    itype = brenda_instance_type(opts, conf)
    snapshots = aws.get_snapshots(conf)
    bdm, snap_description, istore_dev = aws.blk_dev_map(opts, conf, itype, snapshots)
    script = startup_script(opts, conf, istore_dev)
    user_data = None
    if not opts.idle:
        user_data = script
    ssh_key_name = conf.get("SSH_KEY_NAME", "brenda")
    sec_groups = (conf.get("SECURITY_GROUP", "brenda"),)
    run_args = {
        'ImageId'      : ami_id,
        'MaxCount'     : opts.n_instances,
        'InstanceType' : itype,
        'UserData'     : user_data,
        'KeyName'      : ssh_key_name,
        'SecurityGroups' : sec_groups,
        'BlockDeviceMappings' : bdm,
        }

    print("----------------------------")
    print("AMI ID:", ami_id)
    print("Instance type:", itype)
    print("Max instances:", opts.n_instances)
    if snap_description:
        print("Project EBS snapshot:", snap_description)
    if istore_dev:
        print("Instance store device:", istore_dev)
    print("SSH key name:", ssh_key_name)
    print("Security groups:", sec_groups)
    print_script(opts, conf, script)
    aws.get_done(opts, conf) # sanity check on DONE var
    if not opts.dry_run:
        ec2 = aws.get_ec2_client(conf)
        reservation = ec2.create_instances(**run_args)
        print(reservation)

def spot(opts, conf):
    ami_id = utils.get_opt(opts.ami, conf, 'AMI_ID', default=AMI_ID, must_exist=True)
    price = utils.get_opt(opts.price, conf, 'BID_PRICE', must_exist=True)
    reqtype = 'persistent' if opts.persistent else 'one-time'
    itype = brenda_instance_type(opts, conf)
    snapshots = aws.get_snapshots(conf)
    bdm, snap_description, istore_dev = aws.blk_dev_map(opts, conf, itype, snapshots)
    script = startup_script(opts, conf, istore_dev)
    user_data = None
    if not opts.idle:
        user_data = script
    ssh_key_name = conf.get("SSH_KEY_NAME", "brenda")
    sec_groups = (conf.get("SECURITY_GROUP", "brenda"),)
    launch_spec = {}
    launch_spec['ImageId'] = ami_id
    launch_spec['InstanceType'] = itype
    launch_spec['UserData'] = user_data
    launch_spec['KeyName'] = ssh_key_name
    launch_spec['SecurityGroups'] = sec_groups
    launch_spec['BlockDeviceMappings'] = bdm
    if opts.availability_zone:
         launch_spec['Placement'] = opts.availability_zone
    run_args = {
        'SpotPrice'         : price,
        'Type'          : reqtype,
        'InstanceCount'         : opts.n_instances,
        'LaunchSpecification': launch_spec
        }

    print("----------------------------")
    print("AMI ID:", ami_id)
    print("Max bid price", price)
    print("Request type:", reqtype)
    print("Instance type:", itype)
    print("Instance count:", opts.n_instances)
    if opts.availability_zone:
         print("Availability zone:", opts.availability_zone)
    if snap_description:
        print("Project EBS snapshot:", snap_description)
    if istore_dev:
        print("Instance store device:", istore_dev)
    print("SSH key name:", ssh_key_name)
    print("Security groups:", sec_groups)
    print_script(opts, conf, script)
    aws.get_done(opts, conf) # sanity check on DONE var
    if not opts.dry_run:
        ec2 = aws.get_ec2_client(conf)
        reservation = ec2.request_spot_instances(**run_args)
        print(reservation)

def price(opts, conf):
    ec2 = aws.get_ec2_client(conf)
    itype = brenda_instance_type(opts, conf)
    data = {}
    for item in ec2.describe_spot_price_history(InstanceTypes=[itype],
                                                ProductDescriptions=["Linux/UNIX"]).get('SpotPriceHistory'):
        # show the most recent price for each availability zone
        if item.get('AvailabilityZone') in data:
            if item.get('Timestamp') > data[item.get('AvailabilityZone')].get('Timestamp'):
                data[item.get('AvailabilityZone')] = item
        else:
            data[item.get('AvailabilityZone')] = item

    print("Spot price data for instance", itype)
    for k, v in sorted(data.items()):
        print("%s %s $%s" % (v.get('AvailabilityZone'), v.get('Timestamp'), v.get('SpotPrice')))

def stop(opts, conf):
    instances = aws.filter_instances(opts, conf)
    iids = [i.id for i in instances]
    aws.shutdown(opts, conf, iids)

def cancel(opts, conf):
    ec2 = aws.get_ec2_client(conf)
    request_ids = [r.get('SpotInstanceRequestId') for r in ec2.describe_spot_instance_requests().get('SpotInstanceRequests')]
    print("CANCEL", request_ids)
    if not opts.dry_run and len(request_ids) > 0:
        ec2.cancel_spot_instance_requests(SpotInstanceRequestIds=request_ids)

def status(opts, conf):
    ec2 = aws.get_ec2_client(conf)
    instances = aws.filter_instances(opts, conf)
    if instances:
        print("Active Instances")
        now = time.time()
        for i in instances:
            uptime = aws.get_uptime(now, i.launch_time)
            print(' ', i.image_id, aws.format_uptime(uptime), i.public_dns_name)
    requests = ec2.describe_spot_instance_requests().get('SpotInstanceRequests')
    if requests:
        print("Spot Requests")
        for r in requests:
            dns_name = ''
            print("  %s %s %s $%s %s %s" % (r.get('SpotInstanceRequestId'), r.get('Type'), r.get('ValidFrom'), r.get('SpotPrice'), r.get('State'), r.get('Status').get('Message')))

def script(opts, conf):
    itype = brenda_instance_type(opts, conf)
    snapshots = aws.get_snapshots(conf)
    bdm, snap_description, istore_dev = aws.blk_dev_map(opts, conf, itype, snapshots)
    script = startup_script(opts, conf, istore_dev)
    print(script)

def init(opts, conf):
    ec2 = aws.get_ec2_client(conf)

    # create ssh key pair
    if not opts.no_ssh_keys:
        try:
            ssh_key_name = conf.get("SSH_KEY_NAME", "brenda")
            if not opts.aws_ssh_pull and aws.local_ssh_keys_exist(opts, conf):
                # push local ssh public key to AWS
                pubkey_fn = aws.get_ssh_pubkey_fn(opts, conf)
                print("Pushing ssh public key %r to AWS under %r key pair." % (pubkey_fn, ssh_key_name))
                with open(pubkey_fn) as f:
                    pubkey = f.read()
                    res = ec2.import_key_pair(KeyName=ssh_key_name, PublicKeyMaterial=pubkey)
                    print(res)
            else:
                # get new ssh public key pair from AWS
                brenda_ssh_ident_fn = aws.get_brenda_ssh_identity_fn(opts, conf, mkdir=True)
                print("Fetching ssh private key from AWS into %r under %r key pair." % (brenda_ssh_ident_fn, ssh_key_name))
                keypair = ec2.create_key_pair(KeyName=ssh_key_name)
                with open(brenda_ssh_ident_fn, 'w') as f:
                    pass
                os.chmod(brenda_ssh_ident_fn, 0o600)
                with open(brenda_ssh_ident_fn, 'w') as f:
                    f.write(keypair.material)
        except Exception as e:
            print("Error creating ssh key pair", e)

    # create security group
    if not opts.no_security_group:
        try:
            sec_group = conf.get("SECURITY_GROUP", "brenda")
            print("Creating AWS security group %r." % (sec_group,))
            sg = ec2.create_security_group(sec_group, 'Brenda security group')
            sg.authorize('tcp', 22, 22, '0.0.0.0/0')  # ssh
            sg.authorize('icmp', -1, -1, '0.0.0.0/0') # all ICMP
        except Exception as e:
            print("Error creating security group", e)

def reset_keys(opts, conf):
    ec2 = aws.get_ec2_client(conf)

    # remove ssh keys
    if not opts.no_ssh_keys:
        try:
            ssh_key_name = conf.get("SSH_KEY_NAME", "brenda")
            print("Removing AWS ssh key pair %r." % (ssh_key_name,))
            ec2.delete_key_pair(KeyName=ssh_key_name)
            brenda_ssh_ident_fn = aws.get_brenda_ssh_identity_fn(opts, conf)
            if os.path.exists(brenda_ssh_ident_fn):
                print("Removing AWS local ssh identity %r." % (brenda_ssh_ident_fn,))
                os.remove(brenda_ssh_ident_fn)
        except Exception as e:
            print("Error removing ssh key pair", e)

    # remove security group
    if not opts.no_security_group:
        try:
            sec_group = conf.get("SECURITY_GROUP", "brenda")
            print("Removing AWS security group %r." % (sec_group,))
            ec2.delete_security_group(GroupName=sec_group)
        except Exception as e:
            print("Error removing security group", e)

def startup_script(opts, conf, istore_dev):
    login_dir = "/root"

    head = "#!/bin/bash\n"

    # use EC2 instance store on render farm instance?
    use_istore = int(conf.get('USE_ISTORE', '1' if istore_dev else '0'))

    if use_istore:
        # script to start brenda-node running
        # on the EC2 instance store
        iswd = conf.get('WORK_DIR', '/mnt/brenda')
        if iswd != login_dir:
            head += """\
# run Brenda on the EC2 instance store volume
B="%s"
if ! [ -d "$B" ]; then
  for f in brenda.pid log task_count task_last DONE ; do
    ln -s "$B/$f" "%s/$f"
  done
fi
export BRENDA_WORK_DIR="."
mkdir -p "$B"
cd "$B"
""" % (iswd, login_dir)
        else:
            head += 'cd "%s"\n' % (login_dir,)
    else:
        head += 'cd "%s"\n' % (login_dir,)

    head += "/usr/local/bin/brenda-node --daemon <<EOF\n"
    tail = "EOF\n"
    keys = [
        'AWS_ACCESS_KEY',
        'AWS_SECRET_KEY',
        'BLENDER_PROJECT',
        'WORK_QUEUE',
        'RENDER_OUTPUT'
        ]
    optional_keys = [
        "S3_REGION",
        "SQS_REGION",
        "CURL_MAX_THREADS",
        "CURL_N_RETRIES",
        "CURL_DEBUG",
        "VISIBILITY_TIMEOUT",
        "VISIBILITY_TIMEOUT_REASSERT",
        "N_RETRIES",
        "ERROR_PAUSE",
        "RESET_PERIOD",
        "BLENDER_PROJECT_ALWAYS_REFETCH",
        "WORK_DIR",
        "SHUTDOWN",
        "DONE"
        ] + list(aws.additional_ebs_iterator(conf))

    script = head
    for k in keys:
        v = conf.get(k)
        if not v:
            raise ValueError("config key %r must be defined" % (k,))
        script += "%s=%s\n" % (k, v)
    for k in optional_keys:
        if k == "WORK_DIR" and use_istore:
            continue
        v = conf.get(k)
        if v:
            script += "%s=%s\n" % (k, v)
    script += tail
    return base64.b64encode(script.encode()).decode("ascii")

def print_script(opts, conf, script):
    if not opts.idle:
        print("Startup Script:")
        for line in script.splitlines():
            for redact in ('AWS_ACCESS_KEY=', 'AWS_SECRET_KEY='):
                if line.startswith(redact):
                    line = redact + "[redacted]"
                    break
            print('  ', line)

def brenda_instance_type(opts, conf):
    return utils.get_opt(opts.instance_type, conf, 'INSTANCE_TYPE', default="m2.xlarge")
