from __future__ import division
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

from future import standard_library
standard_library.install_aliases()
from builtins import str
from past.utils import old_div
import os, time, datetime, calendar, urllib.request, urllib.error, urllib.parse
import boto3
from brenda import utils
from brenda.error import ValueErrorRetry
from brenda.ami import AMI_ID

def aws_creds(conf):
    return {
        'aws_access_key_id' : conf['AWS_ACCESS_KEY'],
        'aws_secret_access_key' : conf['AWS_SECRET_KEY'],
        }

def get_conn(conf, resource_type="s3"):
    region = conf.get('S3_REGION')
    if region:
        conn = boto3.resource(resource_type, region_name=region, **aws_creds(conf))
        if not conn:
            raise ValueErrorRetry("Could not establish {} connection to region {}".format(resource_type, region))
    else:
        conn = boto3.resource(resource_type, **aws_creds(conf))
    return conn

def get_ec2_client(conf):
    region = conf.get('S3_REGION')
    resource_type = "ec2"
    if region:
        conn = boto3.client(resource_type, region_name=region, **aws_creds(conf))
        if not conn:
            raise ValueErrorRetry("Could not establish {} connection to region {}".format(resource_type, region))
    else:
        conn = boto3.client(resource_type, **aws_creds(conf))
    return conn

def parse_s3_url(url):
    if url.startswith('s3://'):
        return url[5:].split('/', 1)

def s3_get(conf, s3url, dest, etag=None):
    """
    High-speed download from S3 that can use multiple simultaneous
    download threads to optimize the downloading of a single file.
    S3 file is given in s3url (using s3://BUCKET/FILE naming
    convention) and will be saved in dest.  If etag from previous
    download is provided, and file hasn't changed since then, don't
    download the file and instead raise an exception of type
    paracurl.Exception where the first element of the exception
    tuple == paracurl.PC_ERR_ETAG_MATCH.  Returns tuple of
    (file_length, etag).
    """

    paracurl_kw = {
        'max_threads' : int(conf.get('CURL_MAX_THREADS', '16')),
        'n_retries' : int(conf.get('CURL_N_RETRIES', '4')),
        'debug' : int(conf.get('CURL_DEBUG', '1'))
        }
    if etag:
        paracurl_kw['etag'] = etag
    s3tup = parse_s3_url(s3url)
    if not s3tup or len(s3tup) != 2:
        raise ValueError("s3_get: bad s3 url: %r" % (s3url,))
    conn = get_conn(conf, "s3")
    buck = conn.Bucket(s3tup[0])
    object_ref = conn.Object(buck.name,s3tup[1])
    key = object_ref.get()
    etag = key['ETag']
    content_len = key['ContentLength']
    body = key['Body'].read()
    with open(dest, 'wb') as file_out:
        file_out.write(body)
    return content_len, etag

def put_s3_file(conf, bucktup, path, s3name):
    """
    bucktup is the return tuple of get_s3_output_bucket_name
    """

    conn = get_conn(conf, "s3")

    object_ref = conn.Object(bucktup[1][0],bucktup[1][1] + s3name)
    object_ref.put(Body=open(path, 'rb'), StorageClass='REDUCED_REDUNDANCY')


def format_s3_url(bucktup, s3name):
    """
    bucktup is the return tuple of get_s3_output_bucket_name
    """
    return "s3://%s/%s%s" % (bucktup[1][0], bucktup[1][1], s3name)

def get_s3_output_bucket_name(conf):
    bn = conf.get('RENDER_OUTPUT')
    if not bn:
        raise ValueError("RENDER_OUTPUT not defined in configuration")
    bn = parse_s3_url(bn)
    if not bn:
        raise ValueError("RENDER_OUTPUT must be an s3:// URL")
    if len(bn) == 1:
        bn.append('')
    elif len(bn) == 2 and bn[1] and bn[1][-1] != '/':
        bn[1] += '/'
    return bn

def get_s3_output_bucket(conf):
    bn = get_s3_output_bucket_name(conf)
    conn = get_conn(conf, "s3")
    buck = conn.Bucket(bn[0])
    return buck, bn

def parse_sqs_url(url):
    if url.startswith('sqs://'):
        return url[6:]

def get_sqs_work_queue_name(conf):
    qname = conf.get('WORK_QUEUE')
    if not qname:
        raise ValueError("WORK_QUEUE not defined in configuration")
    qname = parse_sqs_url(qname)
    if not qname:
        raise ValueError("WORK_QUEUE must be an sqs:// URL")
    return qname

def create_sqs_queue(conf):
    visibility_timeout = int(conf.get('VISIBILITY_TIMEOUT', '120'))
    qname = get_sqs_work_queue_name(conf)
    conn = get_conn(conf, "sqs")
    return conn.create_queue(QueueName=qname, Attributes={'VisibilityTimeout': str(visibility_timeout)})

def get_sqs_conn_queue(conf):
    qname = get_sqs_work_queue_name(conf)
    conn = get_conn(conf, "sqs")
    return conn.get_queue_by_name(QueueName=qname), conn

def get_sqs_queue(conf):
    return get_sqs_conn_queue(conf)[0]

def write_sqs_queue(string, queue):
    queue.send_message(MessageBody=string)

def get_ec2_instances_from_conn(conn, instance_ids=None):
    filter_args = {}

    if instance_ids:
        filter_args['InstanceIds'] = instance_ids
    reservations = conn.instances.filter(**filter_args)
    return [r for r in reservations]

def get_ec2_instances(conf, instance_ids=None):
    conn = get_conn(conf, "ec2")
    return get_ec2_instances_from_conn(conn, instance_ids)

def get_snapshots(conf):
    conn = get_conn(conf, "ec2")
    return conn.snapshots.all()

def get_volumes(conf):
    conn = get_conn(conf, "ec2")
    return conn.get_all_volumes()

def find_snapshot(snapshots, name):
    for s in snapshots:
        try:
            if s.tags['Name'] == name:
                return s.id
        except:
            pass

def find_volume(volumes, name):
    for v in volumes:
        try:
            if v.tags['Name'] == name:
                return v.id
        except:
            pass

def format_uptime(sec):
    return str(datetime.timedelta(seconds=sec))

def get_uptime(now, aws_launch_time):
    return int(now - aws_launch_time.timestamp())

def filter_instances(opts, conf, hostset=None):
    def threshold_test(aws_launch_time):
        ut = get_uptime(now, aws_launch_time)
        return (old_div(ut, 60)) % 60 >= opts.threshold

    now = time.time()
    ami = utils.get_opt(opts.ami, conf, 'AMI_ID', default=AMI_ID)
    if opts.imatch:
        imatch = frozenset(opts.imatch.split(','))
    else:
        imatch = None
    if hostset is None:
        if getattr(opts, 'hosts_file', None):
            with open(opts.hosts_file, 'r') as f:
                hostset = frozenset([line.strip() for line in f.readlines()])
        elif getattr(opts, 'host', None):
            hostset = frozenset((opts.host,))
    inst = [i for i in get_ec2_instances(conf)
            if i.image_id and i.public_dns_name
            and threshold_test(i.launch_time)
            and (imatch is None or i.instance_type in imatch)
            and (ami is None or ami == i.image_id)
            and (hostset is None or i.public_dns_name in hostset)]
    inst.sort(key = lambda i : (i.image_id, i.launch_time, i.public_dns_name))
    return inst

def shutdown_by_public_dns_name(opts, conf, dns_names):
    iids = []
    for i in get_ec2_instances(conf):
        if i.public_dns_name in dns_names:
            iids.append(i.instance_id)
    shutdown(opts, conf, iids)

def shutdown(opts, conf, iids):
    # Note that persistent spot instances must be explicitly cancelled,
    # or EC2 will automatically requeue the spot instance request
    if opts.terminate:
        print("TERMINATE", iids)
        if not opts.dry_run and iids:
            conn = get_conn(conf, "ec2")
            cancel_spot_requests_from_instance_ids(conn, instance_ids=iids)
            conn.terminate_instances(instance_ids=iids)
    else:
        print("SHUTDOWN", iids)
        if not opts.dry_run and iids:
            conn = get_conn(conf, "ec2")
            cancel_spot_requests_from_instance_ids(conn, instance_ids=iids)
            conn.stop_instances(instance_ids=iids)

def get_ssh_pubkey_fn(opts, conf):
    v = conf.get('SSH_PUBKEY')
    if not v:
        v = os.path.join(os.path.expanduser("~"), '.ssh', 'id_rsa.pub')
    return v

def get_ssh_identity_fn(opts, conf):
    v = conf.get('SSH_IDENTITY')
    if not v:
        v = os.path.join(os.path.expanduser("~"), '.ssh', 'id_rsa')
    return v

def get_brenda_ssh_identity_fn(opts, conf, mkdir=False):
    ssh_dir = os.path.join(os.path.expanduser("~"), '.ssh')
    if mkdir and not os.path.isdir(ssh_dir):
        os.mkdir(ssh_dir)
    return os.path.join(ssh_dir, "id_rsa.brenda")

def local_ssh_keys_exist(opts, conf):
    return (os.path.exists(get_ssh_pubkey_fn(opts, conf))
            and os.path.exists(get_ssh_identity_fn(opts, conf))
            and not os.path.exists(get_brenda_ssh_identity_fn(opts, conf)))

def get_adaptive_ssh_identity_fn(opts, conf):
    fn = get_brenda_ssh_identity_fn(opts, conf)
    if not os.path.exists(fn):
        fn = get_ssh_identity_fn(opts, conf)
        if not os.path.exists(fn):
            raise ValueError("No ssh private key exists, did you run 'brenda-run init'?")
    return fn

def get_default_ami_with_fmt(fmt):
    if AMI_ID:
        return fmt % (AMI_ID,)
    else:
        return ""

def parse_ebs_url(key):
    if key and key.startswith("ebs://"):
        return key[6:]

def project_ebs_snapshot(conf):
    return parse_ebs_url(conf.get('BLENDER_PROJECT'))

def translate_snapshot_name(conf, snap_name, snapshots=None):
    if snap_name:
        if snap_name.startswith('snap-'):
            return snap_name
        else:
            if snapshots is None:
                snapshots = get_snapshots(conf)
            n = find_snapshot(snapshots, snap_name)
            if not n or not n.startswith('snap-'):
                raise ValueError("snapshot not found: %r" % (snap_name,))
            return n

def translate_volume_name(conf, vol_name, volumes=None):
    if vol_name:
        if vol_name.startswith('vol-'):
            return vol_name
        else:
            if volumes is None:
                volumes = get_volumes(conf)
            n = find_volume(volumes, vol_name)
            if not n or not n.startswith('vol-'):
                raise ValueError("volume not found: %r" % (vol_name,))
            return n

def get_work_dir(conf):
    work_dir = os.path.realpath(conf.get('WORK_DIR', '.'))
    if not os.path.isdir(work_dir):
        utils.makedirs(work_dir)
    return work_dir

def add_instance_store(opts, conf, blkprops, itype):
    if not itype.startswith('t1.'):
        dev = utils.blkdev(0, istore=True)
        blkprops['DeviceName'] = dev
        blkprops['Ebs'] = {'VolumeSize': 4, 'DeleteOnTermination': True}
        return dev

def additional_ebs_iterator(conf):
    i = 0
    while True:
        key = "ADDITIONAL_EBS_%d" % (i,)
        if key in conf:
            yield key
        else:
            break
        i += 1

def blk_dev_map(opts, conf, itype, snapshots):
    if not int(conf.get('NO_EBS', '0')):
        bdm = []
        block_device = {}
        snap = project_ebs_snapshot(conf)
        snap_id = translate_snapshot_name(conf, snap, snapshots)
        snap_description = []
        if snap_id:
            dev = utils.blkdev(0)
            block_device['DeviceName'] = dev
            block_device['Ebs']['SnapshotId'] = snap_id
            block_device['Ebs']['DeleteOnTermination'] = True
            snap_description.append((snap, snap_id, dev))
            bdm.append(block_device)
        i = 0
        for k in additional_ebs_iterator(conf):
            i += 1

            temp_block_device = {}
            snap = parse_ebs_url(conf[k].split(',')[0])
            snap_id = translate_snapshot_name(conf, snap, snapshots)
            if snap_id:
                dev = utils.blkdev(i)
                temp_block_device['DeviceName'] = dev
                temp_block_device['Ebs']['SnapshotId'] = snap_id
                temp_block_device['Ebs']['DeleteOnTermination'] = True
                bdm.append(temp_block_device)
                snap_description.append((snap, snap_id, dev))
        istore_block_device = {}
        istore_dev = add_instance_store(opts, conf, istore_block_device, itype)
        bdm.append(istore_block_device)
        return bdm, snap_description, istore_dev
    else:
        return None, None, None

def mount_additional_ebs(conf, proj_dir):
    i = 0
    for k in additional_ebs_iterator(conf):
        i += 1
        dir = os.path.realpath(os.path.join(proj_dir, conf[k].split(',')[1]))
        dev = utils.blkdev(i, mount_form=True)
        utils.mount(dev, dir)

def get_instance_id_self():
    req = urllib.request.Request("http://169.254.169.254/latest/meta-data/instance-id")
    response = urllib.request.urlopen(req)
    the_page = response.read()
    return the_page

def get_spot_request_dict(conf):
    ec2 = get_conn(conf, "ec2")
    requests = ec2.describe_spot_instance_requests()
    return dict([(sir.get('SpotInstanceRequestId'), sir) for sir in requests])

def get_spot_request_from_instance_id(conf, iid):
    instances = get_ec2_instances(conf, instance_ids=(iid,))
    if instances:
        return instances[0].spot_instance_request_id

def cancel_spot_request(conf, sir):
    conn = get_conn(conf, "ec2")
    conn.cancel_spot_instance_requests(SpotInstanceRequestIds=(sir,))

def cancel_spot_requests_from_instance_ids(conn, instance_ids):
    instances = get_ec2_instances_from_conn(conn, instance_ids=instance_ids)
    sirs = [ i.get('SpotInstanceRequestId') for i in instances if i.get('SpotInstanceRequestId') ]
    print("CANCEL", sirs)
    if sirs:
        conn.cancel_spot_instance_requests(SpotInstanceRequestIds=sirs)

def config_file_name():
    config = os.environ.get("BRENDA_CONFIG")
    if not config:
        home = os.path.expanduser("~")
        config = os.path.join(home, ".brenda.conf")
    return config

def validate_done(d):
    done_choices = ('exit', 'shutdown', 'poll')
    if d not in done_choices:
        raise ValueError("DONE config var must be one of %r" % (done_choices,))

def get_done(opts, conf):
    if getattr(opts, 'shutdown', False):
        return 'shutdown'
    else:
        d = conf.get('DONE')
        if d:
            validate_done(d)
            return d
        else:
            sd = int(conf.get('SHUTDOWN', '0'))
            return 'shutdown' if sd else 'exit'
