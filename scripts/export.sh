#!/bin/bash

echo -n "Input blog post ID to export: "
read id

echo -n "Input export file name: "
read export_name

echo "Exporting blog post " $id " to " $export_name

touch $export_name
sudo docker run -it --entrypoint python3 -v "$(pwd)/edaweb.conf":/app/edaweb.conf -v "$(pwd)/edaweb.conf":/app/edaweb/edaweb.conf -v "$(pwd)/$export_name":/app/$export_name --network mariadb --rm reg.reaweb.uk/edaweb /app/edaweb/parser.py export -i $id -u root -o $export_name
