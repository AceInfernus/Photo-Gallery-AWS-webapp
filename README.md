# Photo-Gallery-AWS-webapp
Photo gallery web application user and admin programs

## User web application features:

* Landing page features new account registration and option for existing users to login.
* Each user's homepage shows thumbnails of the pictures uploaded so far.
* Images are stored in an S3 bucket and a MySQL database is used to keep track of username, password and stored images.
* Each user webapp code is scripted to run on startup of an EC2 instance and the EC2 instance image is saved for replication when the web app 
  would need to serve more users than could be handled by one server.
* The upload image feature does not allow invalid files such as pdf, txt etc. to be uploaded into the S3 bucket.


## Admin web application features:

* Shows the list of all EC2 instances running the 'User webapp'.
* Allows manual addition and deletion of User webapp EC2 instances.
* Adds and removes User webapp EC2 instances from the Load Balancer. 
* Can delete all user information and images stored if necessary.
* There are options for viewing CPU utilization and network utilization of the running User webapp EC2 instances.
* Forms are present which can be used to configure thresholds for expanding and shrinking
  the worker pool. It also includes the ratio by which to expand and shrink. For example, an
  expand ratio of 2 doubles the number of workers and a shrink ratio of 4 reduces the number
  of workers by 75%.