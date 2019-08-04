Brenda
======

Brenda uses Amazon EC2, S3, and SQS to implement a distributed
render farm using low-cost EC2 spot instances.  Using Brenda,
you can accelerate complex render tasks by distributing the
work to tens, hundreds, or even thousands of virtual machines
in the cloud.

Brenda is specifically designed to take advantage of the
lower-cost EC2 spot market and is fault-tolerant against
instances being created and terminated at random during
the course of a render job, as is often the case with spot
market volatility.

Table of contents
-----------------

### Introduction
* [James Yonan's talk](#james-yonans-talk)
* [Included tools](#included-tools)
* [Platforms supported](#platforms-supported)

### Tutorial (basic use)
* [First steps](#first-steps)
* [EC2 key pair setup](#ec2-key-pair-setup)
* [Files store considerations (S3 or EBS)](#file-store-considerations-s3-or-ebs)
* [Uploading your project](#uploading-your-project)
* [Local Brenda configuration](#local-brenda-configuration)
* [About the render queue](#about-the-render-queue)
* [Adding jobs to the queue](#adding-jobs-to-the-queue)
* [One-time initialization](#one-time-initialization)
* [Checking prices on instance types](#checking-prices-on-instance-types)
* [Provisioning render nodes](#provisioning-render-nodes)
* [Checking the status of render node instances](#checking-the-status-of-render-node-instances)
* [Tracking the status of a job](#tracking-the-status-of-a-job)
* [Recovery from spot instance termination](#recovery-from-spot-instance-termination)
* [Retrieving rendered frames](#retrieving-rendered-frames)
* [Accessing error log files](#accessing-error-log-files)
* [Shutting things down](#shutting-things-down)

### Advanced features
* [Advanced shutdown procedures](#advanced-shutdown-procedures)
* [Enabling GPU rendering](#enabling-gpu-rendering)
* [Choosing a region](#choosing-another-region)
* [Choosing an availability zone](#choosing-an-availability-zone)
* [Performance evaluation](#performance-evaluation)
* [Subframe rendering](#subframe-rendering)
* [Multiframe rendering](#multiframe-rendering)
* [Rendering large projects using EBS snapshots](#rendering-large-projects-using-ebs-snapshots)
* [Uploading your project data to the AWS cloud](#uploading-your-project-data-to-the-aws-cloud)
* [How to create a Brenda AMI](#how-to-create-a-brenda-ami)

Introduction
------------

### James Yonan's talk

You can view James Yonan's Brenda talk at Blender
Conference 2013 here:

  http://www.youtube.com/watch?v=_Oqo383uviw

Talk notes are in doc/brenda-talk-blendercon-2013.pdf

### Included tools

Brenda includes five tools which are outlined below.  To see
detailed help for each tool, run the tool with the -h option.

1. __brenda-work__ – used to create and populate an SQS queue with
   render tasks.  A render task is a short (often one-line) shell
   script that runs Blender to render a single frame or subframe
   in a project.  Uses the SQS API.

2. __brenda-run__ – used to start EC2 instances running Brenda,
   either as on-demand instances or spot instances at a given
   maximum bid price.  Uses the EC2 API.

3. __brenda-tool__ – used to monitor the operation of an EC2 render
   farm.  It allows an ssh or rsync command to be simultaneously
   executed on all nodes in the farm.  Uses EC2 API and requires
   a standard unix shell where ssh and rsync are available and
   can be run from the command line.

4. __brenda-ebs__ – a simple tool that creates a new EBS volume of
   a specified size and attaches it to a newly started t1.micro
   EC2 instance.

5. __brenda-node__ – worker script to be run on the render farm nodes
   themselves.  It reads tasks from an SQS queue, executes the task
   (usually render operations), and copies the task products (such
   as rendered PNG frames) to S3.  brenda-node is usually not run
   directly by the user, but is remotely instantiated by brenda-run.
   Uses the SQS and S3 APIs.

### Platforms supported

The Brenda client software is command-line oriented and has currently
been tested on macOS and Linux only.

Tutorial (basic use)
--------------------

### First steps

This tutorial is intended for use on macOS or Linux, and Python 2 is required.

If you don't have an AWS (Amazon Web Services) account, sign up
for one now.

First, install the "boto" python library.  This library is used by
Brenda to interact with AWS.

Next, download and install Brenda on the client machine.

    $ git clone http://github.com/gwhobbs/brenda.git
    $ cd brenda
    $ python setup.py install

### EC2 key pair setup

You will need an RSA-based SSH key to access the VMs (virtual machines) that
we will spawn using the AWS EC2 service.  These VMs are often referred to as
"instances", and we will be creating many of these to act as worker nodes in
our render farm.

If you have an existing ssh key pair in ~/.ssh/id_rsa.pub and ~/.ssh/id_rsa,
the Brenda client software will use it.  Otherwise, the software will generate
a new key pair on AWS and download the private key to ~/.ssh/id_rsa.brenda

Next, obtain the AWS "Access Key" and "Secret Key" from the AWS
management console.  These credentials will allow the Brenda
client tools to access AWS resources in your account.

### File store considerations (S3 or EBS)

We will also need a tool for accessing the AWS S3 file store, because we
will be using S3 for two purposes:

1. As a storage location for our Blender project, to allow the render farm
   nodes to access it.

2. As a storage location for final rendered frames generated by the render
   farm.

For this, download and install the "s3cmd" tool.  You will need to configure
s3cmd with your AWS account credentials:

    $ s3cmd --configure

At this point, we will copy our Blender project, assets, and other
supporting files to the AWS cloud so the render farm can access them.
There are two methods to do this, each with their own advantages
and disadvantages:

1.  Bundle Blender project and supporting files into a zip or tar
    file and push to S3.  S3 is a distributed file storage
    service hosted by AWS.

    __Pros__:  Relatively easy to set up.

    __Cons__:  Starts to be prohibitively slow as data set gets
    into the multi-GB range.

2.  Create an EBS snapshot containing Blender project and
    supporting files.  An EBS volume is a kind of virtual
    hard drive that can be attached EC2 instances.  An
    EBS snapshot is a kind of point-in-time copy of an EBS
    volume that many EC2 instances can concurrently access.

    __Pros__:  Efficient and scalable – EBS snapshots can be up
    to 1 TB in size, and Brenda supports attaching up to
    66 EBS snapshots to each render farm instance.

    __Cons__:  More involved to set up.

Continuing with the tutorial, we will use the S3 method (1), but
note the section "rendering large projects using EBS snapshots"
below if your data set is large and you want to use method (2).

### Uploading your project

Next, we will bundle up our Blender project and save it to S3 so
the render farm can access it (make sure that the Blender project
uses relative paths for file access so that the render farm instances
will be able to follow them).

To do this, create a folder with your .blend file and any other supporting
files necessary to render frames, then compress it using tar or zip.
For example, supposing that the project directory is called "myproject",
run:

    $ tar cfzv myproject.tar.gz myproject

Next, create an S3 "bucket" on AWS to store the myproject.tar.gz file we
created above.  S3 buckets are sort of like folders, but they must have a
globally unique name, and they can only contain flat files, not subfolders.
You can choose a name here for the project bucket which I will hereafter
refer to as PROJECT_BUCKET.

    $ s3cmd mb s3://PROJECT_BUCKET

It is possible that the name you chose for PROJECT_BUCKET is already in
use by someone else.  In this case you will see an error message,
and can retry the command using a different name.

We also need another bucket for the render farm to save the rendered
frames.  We will call this FRAME_BUCKET.  Just like PROJECT_BUCKET
above, you should select a unique name.

    $ s3cmd mb s3://FRAME_BUCKET

Now, we will copy our compressed Blender project file to our S3 project
bucket:

    $ s3cmd put myproject.tar.gz s3://PROJECT_BUCKET

To verify that the file was copied, list the files in the bucket:

    $ s3cmd ls s3://PROJECT_BUCKET

### Local Brenda configuration

Next, we will create a Brenda configuration file.  The Brenda
client tools will look for the configuration file in ~/.brenda.conf

Create ~/.brenda.conf now with the following content, making sure
to replace PROJECT_BUCKET and FRAME_BUCKET with the names you
chose above.

```
INSTANCE_TYPE=m3.xlarge
BLENDER_PROJECT=s3://PROJECT_BUCKET/myproject.tar.gz
WORK_QUEUE=sqs://FRAME_BUCKET
RENDER_OUTPUT=s3://FRAME_BUCKET
DONE=shutdown
```

To explain the above configuration settings in detail:

__INSTANCE_TYPE__ describes the type of EC2 instance (i.e. virtual machine)
that will make up the render farm.  Different instance types offer
different levels of performance and cost.

__BLENDER_PROJECT__ is the name of our project file on S3.  It
can be an s3:// or file:// URL.

__WORK_QUEUE__ is the name of an SQS queue that we will create for the
purpose of staging and sequencing the tasks in our render.

__RENDER_OUTPUT__ is the name of an S3 bucket that will contain our
rendered frames.

__DONE=shutdown__ tells the render farm instances that they should
automatically shut themselves down after the render is complete.

### About the render queue

In the next step, we will create the Work Queue for our render
farm.  A work queue is basically a list of many small scripts
that, when run together, will render all of the frames in our
project.

Brenda's essential purpose is to accelerate the rendering process by
concurrently processing our work queue using tens, hundreds or even
thousands of virtual machines.

For example, one of the scripts in a work queue might
look like this (to render frame 5 of our project):

    blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s 5 -e 5 -j 1 -t 0 -a

Suppose our project contains 240 frames.  Then the work queue
would look like this, where each line is a separate task in the
work queue:

```
blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s 1 -e 1 -j 1 -t 0 -a
blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s 2 -e 2 -j 1 -t 0 -a
blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s 3 -e 3 -j 1 -t 0 -a
 .
 .
 .
blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s 238 -e 238 -j 1 -t 0 -a
blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s 239 -e 239 -j 1 -t 0 -a
blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s 240 -e 240 -j 1 -t 0 -a
```

### Adding jobs to the queue

The first step in creating a work queue is to start with a Script Template.
A script template describes how to run Blender to accomplish a unit of work.
Suppose that we want a unit of work to be the rendering of a single PNG
frame.  In this case, our script template would be this:

    blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s $START -e $END -j $STEP -t 0 -a

Using a text editor, create a file called "frame-template" that
contains the above line.  This is a simple template that is designed
to render one frame at a time (as a more advanced exercise, it is also
possible to create a subframe rendering template that will break the
smallest unit of render work down to a portion of a frame – this
could be used to accelerate the rendering of a still, or to cut
down the time spent processing each unit of work in animations where
each frame takes many computer-hours to render).

Brenda includes a tool called "brenda-work" that allows us to easily
generate a work queue.  Suppose that you want to render the first 240
frames of your project.  Use this command to generate the work queue
using the "frame-template" file we created above:

    $ brenda-work -T frame-template -e 240 push

This will create a work queue to render frames 1 to 240 of your project.

To see the current size of the work queue, run:

    $ brenda-work status

You should see a queue size of 240.

If you make a mistake and want to delete the current queue and start over:

    $ brenda-work reset

### One-time initialization

Finally, as part of our initial setup, we will do a one-time initialization
of a new AWS account to create security group and ssh key profiles.  This
only needs to be done once per AWS account:

    $ brenda-run init

### Checking prices on instance types

At this point, we are ready to start rendering.

One of the more interesting features of AWS is the EC2 spot market.  In this
market, we can rent instances (i.e. virtual machines) by the hour to render
our project at a price considerably less than the on-demand going rate.
While the spot market offers good pricing, the downside is that our instances
can be terminated at any time if the spot price rises above our maximum bid
price.

Let's check the current spot market prices:

    $ brenda-run -i c1.xlarge price

When I run the command now, I see the following:

```
Spot price data for instance c1.xlarge
us-east-1a 2013-10-24T07:32:32.000Z $0.141
us-east-1b 2013-10-24T03:55:49.000Z $0.07
us-east-1c 2013-10-24T02:05:53.000Z $0.07
```

This indicates that the c1.xlarge instance (a reasonably fast VM
with 8 cores) is currently renting for US$0.07 per hour.

AWS offers many different instance types that offer different levels
of performance/cost.  Some of the instances that may be suitable for 
use as render farm workers include:

| Instance                | Baseline Spot Price as of 2019.07      | Notes
| --------                | ---------------------------------      | -----
| c5.xlarge               | US$0.066/hour                          | 
| p2.xlarge (default)     | US$0.341/hour                          | Be sure to add -P `setup_cuda.py` to frame template to enable GPU rendering
| c5.24xlarge             | US$1.555/hour                          | 
| r4.xlarge               | US$0.069/hour                          | Untested
| m3.xlarge               | US$0.0624/hour                         | Untested

To see the current spot price of a given EC2 instance in several
availability zones:

    $ brenda-run -i INSTANCE_TYPE price

At certain times, a given instance might be overbid, in which case
the spot market price can rise considerably above the Baseline Spot
Price.  In general, avoid bidding more than the baseline price
as this can make your renders much more expensive than they need to
be.  If a given instance type is overbid, try using a different
instance type whose price is still at its baseline.

For GPU accelerated rendering, AWS offers a GPU-enabled instance
(cg1.4xlarge), however its price is considerably more than standard
instances, making it a questionable value proposition.

For more info on EC2 instance types see:

  http://aws.amazon.com/ec2/instance-types/

### Provisioning render nodes

Continuing with the tutorial, let's bid on 4 c1.xlarge instances
at US$0.07 per hour.  Note that when you run the following command,
you are agreeing to be charged US$0.28 per hour total to rent 4 VMs
(i.e. US$0.07 x 4 instances).

    $ brenda-run -P -i c1.xlarge -N 4 -p 0.07 spot

Note that we used the -P flag to create our spot instance requests.
This flag tells AWS to make our spot requests "persistent", meaning
that if the spot price for c1.xlarge rises above US$0.07/hour, causing
our instances to be terminated, the spot request will stay in place,
meaning that as soon as the price falls back to US$0.07/hour, our
instances will automatically be restarted so they can continue the
render job.

If the above command succeeds, you will see a list of information that
includes the script that Brenda will push to the new instances and a list
of 4 SpotInstanceRequest objects.

In some cases, during peak periods at the AWS data centers, spot
instances might not be available for a resonable cost.  In this case,
it is possible to use on-demand instances instead (Note however that
on-demand instance are considerably more expensive than spot instances).

    $ brenda-run -i c1.xlarge -N 4 demand

### Checking the status of render node instances

To see the current status of your instances and spot requests:

    $ brenda-run status

If you used the "brenda-run ... spot" command above, you should see a rundown
of your 4 pending instances.

```
Spot Requests
  sir-54b91c35 RegionInfo:us-east-1 one-time 2013-10-24T05:32:16.000Z $0.07 <Status: pending-evaluation>
  sir-97762e35 RegionInfo:us-east-1 one-time 2013-10-24T05:32:16.000Z $0.07 <Status: pending-evaluation>
  sir-aa98a235 RegionInfo:us-east-1 one-time 2013-10-24T05:32:16.000Z $0.07 <Status: pending-evaluation>
  sir-db7e5a35 RegionInfo:us-east-1 one-time 2013-10-24T05:32:16.000Z $0.07 <Status: pending-evaluation>
```

These instances are not yet active but are rather in a "pending-evaluation"
state.  After several minutes, if your given price matches the current spot
market conditions, the instances will be activated.  When this occurs,
the status will show something like this:

```
$ brenda-run status
Active Instances
  ami-0f423cdef7e0d3b82 0:01:51 ec2-107-20-36-70.compute-1.amazonaws.com
  ami-0f423cdef7e0d3b82 0:01:51 ec2-50-16-67-202.compute-1.amazonaws.com
  ami-0f423cdef7e0d3b82 0:01:51 ec2-54-205-52-227.compute-1.amazonaws.com
  ami-0f423cdef7e0d3b82 0:01:50 ec2-54-224-220-141.compute-1.amazonaws.com
Spot Requests
  sir-54b91c35 RegionInfo:us-east-1 one-time 2013-10-24T05:32:16.000Z $0.07 <Status: fulfilled>
  sir-97762e35 RegionInfo:us-east-1 one-time 2013-10-24T05:32:16.000Z $0.07 <Status: fulfilled>
  sir-aa98a235 RegionInfo:us-east-1 one-time 2013-10-24T05:32:16.000Z $0.07 <Status: fulfilled>
  sir-db7e5a35 RegionInfo:us-east-1 one-time 2013-10-24T05:32:16.000Z $0.07 <Status: fulfilled>
```

On the other hand, if you used the "brenda-run ... demand" command
above, your instances should be started immediately:

```
$ brenda-run status
Active Instances
  ami-0f423cdef7e0d3b82 0:00:23 ec2-107-20-72-84.compute-1.amazonaws.com
  ami-0f423cdef7e0d3b82 0:00:23 ec2-54-211-251-85.compute-1.amazonaws.com
  ami-0f423cdef7e0d3b82 0:00:23 ec2-54-226-31-134.compute-1.amazonaws.com
  ami-0f423cdef7e0d3b82 0:00:23 ec2-54-234-204-209.compute-1.amazonaws.com
```

### Tracking the status of a job

At this point, the render job is running.  There are several methods you can
use to track its progress.

Use this command to view the number of pending frames in the work queue:

    $ brenda-work status

The brenda package includes a general purpose tool for executing
commands on the render instances.  For example, to view the end
of the log files on each render instance:

    $ brenda-tool ssh tail log

Or view the current CPU load on each render instance:

    $ brenda-tool ssh uptime

To see the number of tasks (i.e. frames) completed by each render instance:

    $ brenda-tool ssh cat task_count

One of the risks of running spot instances is that your instances can be
terminated without warning if the spot price rises above your maximum
bid price.  In this case, the spot requests status might look like this:

```
$ brenda-run status
Spot Requests
  sir-5dbba434 RegionInfo:us-east-1 one-time 2013-10-23T09:12:30.000Z $0.07 <Status: instance-terminated-by-price>
  sir-64daca34 RegionInfo:us-east-1 one-time 2013-10-23T09:12:30.000Z $0.07 <Status: instance-terminated-by-price>
  sir-9cf0b834 RegionInfo:us-east-1 one-time 2013-10-23T09:12:30.000Z $0.07 <Status: instance-terminated-by-price>
  sir-af53be34 RegionInfo:us-east-1 one-time 2013-10-23T09:12:30.000Z $0.07 <Status: instance-terminated-by-price>
```

### Recovery from spot instance termination

Brenda has actually been designed to recover gracefully from instance
termination and can handle the case where instances are randomly
created and destroyed during the course of the render.  It is able to
do this because no task is permanently removed from the work queue
until the products of the task (rendered frames) have been pushed to
the S3 frame bucket.  In particular,

1. Any instance that is terminated will return all uncompleted tasks
   back to the work queue.

2. brenda-run can be used to create "persistent" spot instances, where
   even if an instance is killed because the spot price increases beyond
   the maximum bid, another will be automatically restarted when the spot
   price once again reaches or falls below the maximum bid you specified
   in the "brenda-run spot" command.  To create a persistent spot
   instance, use the -P flag when running the "brenda-run spot" command.

### Retrieving rendered frames

While the render job progresses, you can view the frames that have been
rendered thus far and copied to the S3 file store:

    $ s3cmd ls s3://FRAME_BUCKET

Because we told the render instances to immediately shut down when the
render completes, the "brenda-run status" command will show no Active
Instances on render completion.  At this point, the "brenda-work status"
command should show a queue size of 0.

To download the frames we rendered, prepare a local directory to accept
the frames:

    $ mkdir frames
    $ s3cmd get -r s3://FRAME_BUCKET frames

### Accessing error log files

If something goes wrong during the render, Brenda will normally not shut
down the instances to give you a chance to download the log files:

    $ mkdir logs
    $ brenda-tool rsync log logs/HOST.log

If you want to cancel the render job and shut down the instances,
there are commands for that as well:

### Shutting things down

Cancel pending spot requests that have not been activated yet:

    $ brenda-run cancel

Kill all active instances:

    $ brenda-run -T stop


Advanced features
-----------------

### Advanced shutdown procedures

The simplest way to stop the render farm after all frames have been rendered
is by setting the config var "DONE=shutdown" in your ~/.brenda.conf file
before you start a run.

Or to force a shutdown of the whole farm right now:

    $ brenda-run -T stop

However, there are some useful variations to the shutdown procedure, such
as the case where you have a large number of instances about to transition
into their next billable hour, but the render farm work queue is almost
(but not quite) empty.

For this case, Brenda includes a "prune" capability to reduce the number of
running instances to a specified value.  For example, to reduce the number
of running instances to 4:

    $ brenda-tool -T prune 4

The prune capability is smart about stopping instances – it will
stop instances that have most recently completed a task, to minimize the
amount of lost work, i.e. tasks terminated before completion.

If you only want prune to consider instances close to transitioning to
their next billable hour, you can use the threshold (-T) parameter.

For example, if you only want prune to consider instances where the
minute field of the uptime value is >= 55 minutes, use a threshold
value of 55:

    $ brenda-tool -T -t 55 prune 4

To try out the command without actually terminating any instances, add
the -d flag (dry run).

### Enabling GPU rendering

If you are using an instance that supports GPU rendering (like p2.xlarge), 
you need to add `-P setup_cuda.py` to the end of your frame template. This
will configure Brenda to use CUDA for rendering and enable the first GPU 
as the CUDA device:

    blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s $START -e $END -j $STEP -t 0 -a -P setup_cuda.py

**Note:** Currently, this only supports single-GPU instances. This issue
has not yet been fixed because, historically, single-GPU instances have
offered the most computing power per dollar.

### Choosing a region

Add this line in your brenda.conf file `EC2_REGION=[region]`, where `[region]` is one of the AWS region codes found [here](http://docs.aws.amazon.com/general/latest/gr/rande.html#ec2_region) under amazon EC2.

Note: you will need a different AMI and AMI ID when you change regions. You may also need to run thorugh part of the setup procedure in the other region (I have not tested this yet.)

### Choosing an availability zone

Sometimes, the default availability zone will not be the cheapest. You can
select an availability zone manually using the -z option on brenda-run 
like so:

`brenda-run -z us-east-1c -N 8 -i m1.medium -p 0.013 -P spot`

### Performance evaluation

AWS has many instance types at various levels of price and performance.

How to determine the optimal instance type for render farm use?

To help answer this question, Brenda contains a tool that will evaluate the
performance of a render-farm run in terms of frames rendered per US$.

First set up a run using "brenda-work ... push" as documented in the tutorial
above, but also add the "-r" flag to randomize the work queue.  This will
help to normalize the average render time per frame for our analysis.

This command will add frames 1 to 500 to the work queue using the
"frame-template" script introduced above in the tutorial:

    $ brenda-work -T frame-template -e 500 -r push

Next, begin a render farm run using the entire set of AWS instances
appropriate for render farm usage.  This script will set up spot instance
requests for all such AWS instance types at their baseline spot price.
Larger numbers of instances for slower instance types are used to balance
the data samples for slower instance types so the results for these
instance types will be statistically significant.  Note that these
instances, if successfully instantiated, will cost US$1.11/hour.

```
#!/bin/bash
brenda-run -N 8 -i m1.medium -p 0.013 -P spot
brenda-run -N 4 -i m1.large -p 0.026 -P spot
brenda-run -N 2 -i m1.xlarge -p 0.052 -P spot
brenda-run -N 2 -i m3.xlarge -p 0.0575 -P spot
brenda-run -N 1 -i m3.2xlarge -p 0.115 -P spot
brenda-run -N 4 -i c1.medium -p 0.018 -P spot
brenda-run -N 1 -i c1.xlarge -p 0.07 -P spot
brenda-run -N 4 -i m2.xlarge -p 0.035 -P spot
brenda-run -N 2 -i m2.2xlarge -p 0.071 -P spot
brenda-run -N 1 -i m2.4xlarge -p 0.14 -P spot
```

Once the instances are up and running, use the following command to
analyze the performance of the run:

    $ brenda-tool perf

The output below is an analysis of an actual render farm run of a 500 frame
fluid simulation, rendered with Cycles at 1920x1080, using a pre-baked fluid.

The output shows the render farm performance by both "Tasks per hour"
and "Tasks per US$".  Note that "Tasks" usually equals "Frames" if you
set up your work queue using the common usage where each task renders
a single frame.

```
Tasks per hour (137.90)
  m2.4xlarge 28.15
  m3.2xlarge 27.75
  c1.xlarge 24.35
  m2.2xlarge 15.52
  m3.xlarge 13.18
  m1.xlarge 11.05
  m2.xlarge 8.49
  m1.large 5.07
  m1.medium 2.77
Tasks per US$
  c1.xlarge 347.81
  m2.xlarge 242.56
  m3.2xlarge 241.29
  m3.xlarge 229.22
  m2.2xlarge 218.53
  m1.medium 213.37
  m1.xlarge 212.46
  m2.4xlarge 201.07
  m1.large 194.91
```

The results of this analysis is that the "c1.xlarge" instance type is
the "winner", rendering 347.81 frames per US$.  Note that these
performance data are contingent on the particular instance type being
available at its baseline spot price.  If a particular instance
type is overbid, the spot instance requests will not be instantiated,
causing no data to be available for that instance type.  If you raise
your bidding price to meet or exceed the market price for overbid
instance types (to force them to run), that would skew the results for
those instance types, pushing them down in the "Tasks per US$"
ranking.


### Subframe rendering

Normally, the smallest unit of work in Brenda is the frame.  While this
is often sufficient, sometimes it is advantageous to use a smaller unit
of work, such as by dividing each frame into a grid of tiles, where each
tile is a separate unit of work.

1.  For example, subframe rendering can accelerate the rendering of
    stills.  Normally a still (because it is a single frame) cannot
    take advantage of render-farm acceleration designed for animation.
    However, subframe rendering allows the work of rendering a single
    frame to be subdivided across many instances, allowing for the
    rendering of stills to be accelerated.

2.  When rendering an animation where each frame takes many
    computer-hours to render, there is always the risk that the
    instance might be terminated before completion, causing the
    loss of all computer time already invested in the unfinished
    frame.  To mitigate this risk, subframe animation can be used
    to cut down the length of time needed to render a unit of work.

To do subframe rendering, we need to create a different task template:

```
cat >subframe.py <<EOF
import bpy
bpy.context.scene.render.border_min_x = $SF_MIN_X
bpy.context.scene.render.border_max_x = $SF_MAX_X
bpy.context.scene.render.border_min_y = $SF_MIN_Y
bpy.context.scene.render.border_max_y = $SF_MAX_Y
bpy.context.scene.render.use_border = True
EOF
blender -b *.blend -P subframe.py -F PNG -o $OUTDIR/frame_######_X-$SF_MIN_X-$SF_MAX_X-Y-$SF_MIN_Y-$SF_MAX_Y -s $START -e $END -j $STEP -t 0 -a
```

Save this template in the file subframe-template, then generate the work
queue as follows.  Assuming that we want to break each frame into 64 8x8
tiles, use the following command to generate a work queue for the first
240 frames:

    brenda-work -T subframe-template -e 240 -X 8 -Y 8 -d push

### Multiframe rendering

Multiframe rendering means that each unit of work processed by the
render farm includes multiple frames (in this sense, it is the opposite
of subframe rendering).  This can be useful when per-frame render
times are small and you want to render multiple frames for each
instantiation of the Blender executable, or when there is a startup
cost associated with rendering a series of frames, and you want to
amoritize that cost over multiple frames.

When generating the work queue, specify the -S option and the number
of frames you would like to group together in each unit of work.
The below example will generate a work queue to render 240 frames
in units of 10 frames each.

```
$ brenda-work -T frame-template -S 10 -e 240 push
blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s 1 -e 10 -j 1 -t 0 -a
blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s 11 -e 20 -j 1 -t 0 -a
blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s 21 -e 30 -j 1 -t 0 -a
.
.
.
blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s 221 -e 230 -j 1 -t 0 -a
blender -b *.blend -F PNG -o $OUTDIR/frame_###### -s 231 -e 240 -j 1 -t 0 -a
```

### Rendering large projects using EBS snapshots

Brenda supports both AWS S3 and EBS snapshots as a means of providing
your project data to the render farm.

While smaller projects can provide the .blend file and other project data
via S3, having each render farm instance download a multi-GB file from
S3 can be prohibitively slow.

An alternative is to use AWS EBS (Elastic Block Store) snapshots instead
of S3 as a means to make your project data and assets available to the
render farm instances.  EBS volumes can be up to 1 TB and Brenda
currently supports up to 66 EBS volumes connected to each render
farm instance.

An EBS volume can be thought of as a kind of virtual hard drive.
You can create an EC2 instance and attach a newly created or existing
EBS volume to that instance, then copy your project files and assets
to the volume.  Your .blend file should be in the top level of the
EBS volume, so Brenda can locate it.  EBS volumes are persistent,
so you can maintain a volume that contains the current state of your
project, while adding, removing, and modifying files as needed.

Brenda has limited support for creating and managing EBS volumes.
For example, to create a new EBS volume that is 4 GB in size, and
attach it to a newly running t1.micro instance on /mnt, use this
command:

    $ brenda-ebs -m -s 4 new

Once the instance is up, you can copy your project files, bakes, 
and data using rsync.  For example, this command will copy
fluid.blend and cache_fluid to the top-level directory of the EBS
volume:

    $ brenda-tool rsync -av fluid.blend cache_fluid HOST:/mnt/

When you are finished copying files to the EBS volume, unmount it and
shut down the instance it is attached to:

    $ brenda-tool ssh umount /mnt
    $ brenda-run stop

An EBS volume, by itself, can only be connected to a single instance
at a time, so before we begin a render, we must "snapshot" the
EBS volume so we can make a copy of it available to all of the instances
in the render farm.  The AWS web console provides a full set of tools
for creating EBS volumes and snapshotting them.

If you created your volume with the "brenda-ebs" command above,
you can snapshot it by going to EC2 / Volumes in the AWS management
console, right click on the volume you just created (you can identify
it by its capacity), select "Create Snapshot", and select a name
for the snapshot.  Creating snapshots is not instantaneous -- go to the
Snapshots panel to verify that the snapshot is complete.  At that
point you might want to clean up by terminating the t1.micro instance we
used to initially access the volume (see Instances panel) and deleting
the volume that the snapshot was based on (see Volume panel).

Once you have your EBS snapshot ready, you can specify it in your
~/.brenda.conf file by using an ebs:// URL:

    BLENDER_PROJECT=ebs://EBS_SNAPSHOT_NAME

EBS_SNAPSHOT_NAME can be a raw snapshot ID such as "snap-ab957cc2"
or it can be a high-level name that you assigned to the snapshot
such as "my-project".

__Note__: When using an EBS snapshot as your BLENDER_PROJECT,
make sure that your .blend file is in the top level of the
EBS volume, so Brenda can locate it.  Also make sure that
all paths used in your .blend file are relative, so that
the render farm instances will be able to follow them.

Brenda also supports mounting additional EBS snapshots (up to 65
more) that appear as subdirectories in your project directory,
and can be used to provide assets and additional data to the
render process.

```
ADDITIONAL_EBS_0="ebs://EBS_SNAPSHOT_NAME,DIRECTORY"
ADDITIONAL_EBS_1="ebs://EBS_SNAPSHOT_NAME,DIRECTORY"
.
.
.
```

The EBS snapshot EBS_SNAPSHOT_NAME will be mounted as a subdirectory
called DIRECTORY in the same directory as your .blend project.


### Uploading your project data to the AWS cloud

To use Brenda, you must first upload your project data to the
AWS cloud so that the data resides on either S3 or an EBS
volume.

When your project data is large, there are various methods
that can be used to optimize this process:

1. Consider generating bakes and caches in the cloud itself so that
   the data is already there and doesn't need to be uploaded.  This
   could be done by starting up a Windows EC2 instance, installing
   Blender and your project files on it, generating the bake/cache
   files, and copying them to an EBS volume.

2. If your project data and assets is large (hundreds of GB or TB),
   it may be impractical to upload on the internet.  One alternative
   is AWS Import/Export:

   http://aws.amazon.com/importexport/

   You can physically ship a storage device (such as a hard drive)
   to an AWS data center, and they will copy the data directly to an
   EBS snapshot, which you can then refer to in your Brenda
   configuration.  See the section above "rendering large projects
   using EBS snapshots" for more info on making your EBS snapshot
   available to the render farm.


### How to create a Brenda AMI

While Brenda already has a link to an existing AMI that has Blender
and Brenda pre-installed, the public AMI is out of date, and you can build your own AMI using the
following procedure.

#### 1. Initial Ubuntu setup
Use the Ubuntu 18.04 x64 AMI as a starting point, then execute these commands as root.

```
$ perl -i -pe 's/disable_root: true/disable_root: false/' /etc/cloud/cloud.cfg
$ perl -i -pe 's/.*(ssh-rsa .*)/\1/' /root/.ssh/authorized_keys
```

#### 2. Install CUDA drivers (if using GPU rendering)
If you want to utilize GPU rendering, you'll need to follow [Amazon's instructions](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/install-nvidia-driver.html) to install the appropriate CUDA driver for your instance type (G2, P2, P3). I have not done thorough testing, but I normally use a fleet of p2.xlarge instances, as this has historically been the best way to get the most GPU power per dollar. I also read somewhere (but have not verified) that 1 GPU per frame is optimal for Cycles renders. 

You also need to create a file to tell Blender to use the GPU for rendering. I put the following in `/opt/cuda_setup.py`:

```python
import bpy

bpy.context.user_preferences.addons['cycles'].preferences.compute_device_type = 'CUDA'
bpy.context.user_preferences.addons['cycles'].preferences.devices[0].use = True
```

Now you can append `-P cuda_setup.py` to your frame template to tell Blender to use the GPU. 

**Note:** This version of `cuda_setup.py` will only work on single-GPU instances. I haven't updated it to support multiple GPUs because, historically, single-GPU instances have seemed to offer the most computing power per dollar. 

#### 3. Blender and general dependencies
```bash
$ add-apt-repository ppa:thomas-schiex/blender
$ apt-get update
$ apt-get install -y blender python-pip gcc python-dev libcurl4-openssl-dev git unzip
$ pip install -U boto
$ pip install -U s3cmd
```

#### 4. Next, download and install Brenda.

```bash
$ git clone http://github.com/gwhobbs/brenda.git
$ cd brenda
$ python setup.py install
```

#### 5. Prepare for publishing (optional)
If you intend to make a public AMI, be sure to clean the instance
filesystem of security-related files before you snapshot it:

```bash
$ rm -rf /root/.bash_history /home/ubuntu/.bash_history
$ rm -rf /root/.cache /home/ubuntu/.sudo_as_admin_successful /home/ubuntu/.cache /var/log/auth.log /var/log/lastlog
$ rm -rf /root/.ssh/authorized_keys /home/ubuntu/.ssh/authorized_keys /root/.ssh/authorized_keys.bak /home/ubuntu/.ssh/authorized_keys.bak
```

Note: make sure not to delete /root/.ssh/authorized_keys until the moment you
are ready to snapshot the instance, because doing so will prevent you from logging
into the instance again by ssh.

#### 6. Save the AMI.
The resulting image will have all dependencies
necessary to run Blender and Brenda.

#### 7. Launch and test
Set `AMI_ID` in your `~/.brenda.conf` like so:

`AMI_ID=ami-0f02c90c31cb257d5`

#### 8. Publish (optional)
If you want to publish the image, go to Modify Image Permissions in the AMI page of the AWS console, and set the image permissions to public. 
