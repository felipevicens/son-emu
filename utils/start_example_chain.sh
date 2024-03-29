#!/bin/bash


# deploy VNFs
son-emu-cli compute start -d datacenter1 -n tsrc -i traffic_source -c ./start.sh
son-emu-cli compute start -d datacenter2 -n fw -i firewall -c ./start.sh
son-emu-cli compute start -d long_data_center_name3 -n tsink -i traffic_sink -c ./start.sh

# setup links in the chain
son-emu-cli network add -src tsrc -dst fw
son-emu-cli network add -src fw -dst tsink
son-emu-cli network add -src tsink -dst tsrc



