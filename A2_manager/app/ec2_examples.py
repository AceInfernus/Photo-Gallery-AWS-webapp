from flask import render_template, redirect, url_for, request, g, session
from app import webapp

import boto3
from app import config
from datetime import datetime, timedelta
from operator import itemgetter
from argparse import ArgumentParser
import threading
import time
import mysql.connector
import math
from app.config import db_config



def connect_to_database():
    return mysql.connector.connect(user=db_config['user'],
                                   password=db_config['password'],
                                   host=db_config['host'],
                                   database=db_config['database'])

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = connect_to_database()
    return db

@webapp.teardown_appcontext
def teardown_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@webapp.route('/',methods=['GET'])
@webapp.route('/index',methods=['GET'])
@webapp.route('/main',methods=['GET'])
# Display an HTML page with links
def main():
    #set the default value of cpu thresholds and ratios
    #by default, cpu thresholds are set to temporarily stop autoscale
    session['cpu1'] = 1
    session['cpu2'] = 0
    session['ratio1'] = 2
    session['ratio2'] = 2

    return render_template("main.html",title="Landing Page")

@webapp.route('/ec2_examples',methods=['GET'])
# Display an HTML list of all ec2 instances
def ec2_list():

    # create connection to ec2
    ec2 = boto3.resource('ec2')

    instances = ec2.instances.filter(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])
    activate_job()

    return render_template("ec2_examples/list.html",title="EC2 Instances",instances=instances)


@webapp.route('/ec2_examples/<id>',methods=['GET'])
#Display details about a specific instance.
def ec2_view(id):
    ec2 = boto3.resource('ec2')

    instance = ec2.Instance(id)

    client = boto3.client('cloudwatch')

    metric_name = 'CPUUtilization'

    ##    CPUUtilization, NetworkIn, NetworkOut, NetworkPacketsIn,
    #    NetworkPacketsOut, DiskWriteBytes, DiskReadBytes, DiskWriteOps,
    #    DiskReadOps, CPUCreditBalance, CPUCreditUsage, StatusCheckFailed,
    #    StatusCheckFailed_Instance, StatusCheckFailed_System


    namespace = 'AWS/EC2'
    statistic = 'Average'                   # could be Sum,Maximum,Minimum,SampleCount,Average



    cpu = client.get_metric_statistics(
        Period=1 * 60,
        StartTime=datetime.utcnow() - timedelta(seconds=60 * 60),
        EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
        MetricName=metric_name,
        Namespace=namespace,  # Unit='Percent',
        Statistics=[statistic],
        Dimensions=[{'Name': 'InstanceId', 'Value': id}]
    )

    cpu_stats = []


    for point in cpu['Datapoints']:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        time = hour + minute/60
        cpu_stats.append([time,point['Average']])

    cpu_stats = sorted(cpu_stats, key=itemgetter(0))

    statistic = 'Sum'  # could be Sum,Maximum,Minimum,SampleCount,Average

    network_in = client.get_metric_statistics(
        Period=1 * 60,
        StartTime=datetime.utcnow() - timedelta(seconds=60 * 60),
        EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
        MetricName='NetworkIn',
        Namespace=namespace,  # Unit='Percent',
        Statistics=[statistic],
        Dimensions=[{'Name': 'InstanceId', 'Value': id}]
    )

    net_in_stats = []

    for point in network_in['Datapoints']:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        time = hour + minute/60
        net_in_stats.append([time,point['Sum']])

    net_in_stats = sorted(net_in_stats, key=itemgetter(0))



    network_out = client.get_metric_statistics(
        Period=5 * 60,
        StartTime=datetime.utcnow() - timedelta(seconds=60 * 60),
        EndTime=datetime.utcnow() - timedelta(seconds=0 * 60),
        MetricName='NetworkOut',
        Namespace=namespace,  # Unit='Percent',
        Statistics=[statistic],
        Dimensions=[{'Name': 'InstanceId', 'Value': id}]
    )


    net_out_stats = []

    for point in network_out['Datapoints']:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        time = hour + minute/60
        net_out_stats.append([time,point['Sum']])

        net_out_stats = sorted(net_out_stats, key=itemgetter(0))


    return render_template("ec2_examples/view.html",title="Instance Info",
                           instance=instance,
                           cpu_stats=cpu_stats,
                           net_in_stats=net_in_stats,
                           net_out_stats=net_out_stats)


@webapp.route('/ec2_examples/create',methods=['POST'])
# Start a new EC2 instance
def ec2_create():

    ec2 = boto3.resource('ec2')
    client = boto3.client('elb')
    cloudwatch = boto3.client('ec2')
    f= ec2.create_instances(ImageId=config.ami_id, InstanceType='t2.small', MinCount=1, MaxCount=1, SecurityGroupIds=['workers security group'], KeyName='ece1779_fall2017',Monitoring= {'Enabled':True})
    for instance in f:
        instance.wait_until_running()
        instance.reload()
        g = instance.id
        response = client.register_instances_with_load_balancer(
            LoadBalancerName='ece1779lb',
            Instances=[
                {
                    'InstanceId': g
                },
            ]
        )

    return redirect(url_for('ec2_list'))



@webapp.route('/ec2_examples/delete/<id>',methods=['POST'])
# Terminate a EC2 instance
def ec2_destroy(id):
    # create connection to ec2
    ec2 = boto3.resource('ec2')
    client = boto3.client('elb')
    response1 = client.deregister_instances_from_load_balancer(
        LoadBalancerName='ece1779lb',
        Instances=[
            {
                'InstanceId': id
            },
        ]
    )
    ec2.instances.filter(InstanceIds=[id]).terminate()

    return redirect(url_for('ec2_list'))

@webapp.before_first_request
def activate_job():
    cpu1 = float(session.get('cpu1', 1))
    cpu2 = float(session.get('cpu2', 0))
    ratio1 = float(session.get('ratio1', 2))
    ratio2 = float(session.get('ratio2', 2))
    def default_autoscale():
        while True:

            scaleup = ratio1 -1
            scaledown = 1 - (1/ratio2)
            cpu_threshold1 = cpu1 # test = 0, normal = 0.8, stop = 1
            cpu_threshold2 = cpu2 #stop = 0, normal = 0.1, test = 1
            ec2 = boto3.resource('ec2')
            instances_check = ec2.instances.all()
            for i in instances_check:
                if i.state['Name'] == 'pending':
                    time.sleep(100)
            instances = ec2.instances.filter(
                Filters=[{'Name': 'instance-state-name', 'Values': ['running']}])
            size = 0

            for i in instances:
                if i.id != 'i-0685094950c4f79b9' and i.id != 'i-0ffc2c8ecb2d62631':
                    size += 1

            up_size = int(scaleup * size)
            down_size = int(scaledown * size)

            if size>=4:
                up_size = 0

            # get cpu_util here!
            client = boto3.client('cloudwatch')

            parser = ArgumentParser(description='EC2 load checker')
            parser.add_argument(
                '-w', action='store', dest='warn_threshold', type=float, default=0.85)
            parser.add_argument(
                '-c', action='store', dest='crit_threshold', type=float, default=0.95)
            arguments = parser.parse_args()
            now = datetime.utcnow()
            past = now - timedelta(minutes=30)
            future = now + timedelta(minutes=10)
            ins = ec2.instances.filter(Filters= [{'Name':'instance-state-name', 'Values': ['running']},
                                                 {'Name': 'instance.group-name','Values':['workers security group']}])
            cpu_list=[]
            for inst in ins:

                results = client.get_metric_statistics(
                    Namespace='AWS/EC2',
                    MetricName='CPUUtilization',
                    Dimensions=[{'Name': 'InstanceId', 'Value': inst.id}],
                    StartTime=past,
                    EndTime=future,
                    Period=300,
                    Statistics=['Average'])

                datapoints = results['Datapoints']
                if(datapoints!=[]):
                    last_datapoint = sorted(datapoints, key=itemgetter('Timestamp'))[-1]
                    utilization = last_datapoint['Average']
                    load = round((utilization/100.0), 2)

                    cpu_list.append(load)
                else:
                    continue

            #compute average load over all instances
            avg = sum(cpu_list)/max(len(cpu_list),1)


            if avg >= cpu_threshold1:
                for i in range(up_size):
                   #this is instance create function
                    ec2 = boto3.resource('ec2')
                    client = boto3.client('elb')
                    cloudwatch = boto3.client('ec2')
                    f= ec2.create_instances(ImageId=config.ami_id, InstanceType='t2.small', MinCount=1, MaxCount=1, SecurityGroupIds=['workers security group'], KeyName='ece1779_fall2017', Monitoring= {'Enabled':True})
                    for instance in f:
                        instance.wait_until_running()
                        instance.reload()
                        g = instance.id
                        response = client.register_instances_with_load_balancer(
                            LoadBalancerName='ece1779lb',
                            Instances=[
                                {
                                    'InstanceId': g
                                },
                            ]
                        )
            count = 0
            for c in ins:
                count+=1


            if avg <= cpu_threshold2 and count>= 2:
                for j in range(down_size):
                    m = 1
                    #this is the instance delete function
                    for i in ins:
                        if count>=2 and i.id != 'i-0685094950c4f79b9' and i.id != 'i-00adff1b3c9491ce2' and i.id != 'i-0ffc2c8ecb2d62631' and m == 1:
                            id = i.id
                            ec2 = boto3.resource('ec2')
                            client = boto3.client('elb')
                            response1 = client.deregister_instances_from_load_balancer(
                                LoadBalancerName='ece1779lb',
                                Instances=[
                                    {
                                        'InstanceId': id
                                    },
                                ]
                            )
                            ec2.instances.filter(InstanceIds=[id]).terminate()
                            m = 0
                            count-=1
            time.sleep(120)

    thread = threading.Thread(target=default_autoscale)
    thread.start()

@webapp.route('/ec2_examples/autoscaling',methods=['POST', 'GET'])
def autoscale():
     # create connection to ec2
    attempted_cpu_threshold1 = request.form.get('threshold1', ' ')
    attempted_cpu_threshold2 = request.form.get('threshold2', ' ')
    attempted_ratio1 = request.form.get('ratio1', ' ')
    attempted_ratio2 = request.form.get('ratio2', ' ')
    if attempted_cpu_threshold1 != ' ' and attempted_cpu_threshold2 != ' ' and attempted_ratio1 != ' ' and attempted_ratio2 != ' ':
        session['cpu1'] = attempted_cpu_threshold1
        session['cpu2'] = attempted_cpu_threshold2
        session['ratio1'] = attempted_ratio1
        session['ratio2'] = attempted_ratio2
    return redirect(url_for('ec2_list'))

@webapp.route('/ec2_examples/delete_all',methods=['POST'])
def delete_all_data():
    s3 = boto3.resource('s3')
    bucket = s3.Bucket('ece1779fall2017photo')
    bucket.objects.all().delete()

    cnx = get_db()
    cursor = cnx.cursor()
    query = "DELETE FROM transformation"
    cursor.execute(query)
    cnx.commit()
    query = "DELETE FROM photo"
    cursor.execute(query)
    cnx.commit()
    query = "DELETE FROM user"
    cursor.execute(query)
    cnx.commit()
    cursor.close()
    cnx.commit()

    return render_template("delete_all_data.html")
