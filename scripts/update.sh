#!/bin/bash

echo -n "Input blog post ID to update: "
read id

sudo docker run -it --entrypoint python3 -v "$(pwd)/edaweb.conf":/app/edaweb.conf -v "$(pwd)/edaweb.conf":/app/edaweb/edaweb.conf -v "$(pwd)/$1":/app/$1 --network mariadb --rm reg.reaweb.uk/edaweb /app/edaweb/parser.py update -i $id -u root -m $1
