# This is socket client for GTAVisionExport
GTAVisionExport managed plugin has socket server on port 5555.
This is webserver + socket client which enables to instruct the managed plugin.

## Installation
Install all needed libraries by `pip install -r requirements.txt`

## Starting
Simply start the server nd socket client by `python main.py`

Make sure you start it after your GTA V is running!

## Accessing it from other devices
If using WAMP server, just copy `index.html` to some place in `www` directory.
Then, if you can not access it from other device in local site (`192.168.0.*` address)
Modify both `httpd.conf` and `httpd-vhosts.conf`
and put `Require ip 192.168.0` right after the `Require local` line, wherever it is.

Id you are using docker, you can set up apache web server on 8082 port by `docker-compose up`

# The gallery

This repo contains browser viewer of the images.
You run it by `docker-compose up`, and it runs the nginx server.
You also need to run the python REST API by `python gallery.py`.

For HTTP 2 you need the HTTPS connection.
For HTTPS you need the certificate.
Start the container by `docker-compose up`.
Enter it by `docker-compose exec nginx-https bash`.
There, generate certificate by 
`openssl req -x509 -newkey rsa:4086 -subj "/C=CZ/ST=CzechRepublic/L=Prague/O=CVUT/CN=localhost" -keyout "/etc/nginx/external/key.pem" -out "/etc/nginx/external/cert.pem" -days 3650 -nodes -sha256
`