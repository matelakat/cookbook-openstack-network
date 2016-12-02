#!/bin/bash
# This script moves routers from one host to another
#
# Usage:
#
#    move-routers.sh <source host> <destination host> <file with router ids>
#
# where <file with router ids> is a file containing router ids, one per line.
#
# The script will iterate through all the routers hosted by <source host> and
# move the ones listed in the file <file with router ids>.

set -eu


function main() {
    local src
    local dst
    local file_with_router_ids

    local src_agent
    local dst_agent

    src="${1:-$(fail_with "Please specify a source host: $(list_l3_hosts)")}"
    dst="${2:-$(fail_with "Please specify a valid destination host: $(list_l3_hosts)")}"
    file_with_router_ids="${3:-$(fail_with "Please specify a file with the list of router ids")}"

    [ -e "$file_with_router_ids" ] || fail_with "The file $file_with_router_ids does not exist"

    src_agent=$(l3_agent_of_host $src)
    dst_agent=$(l3_agent_of_host $dst)

    [ -z "$src_agent" ] && fail_with "Invalid source host ($src), valid ones are: $(list_l3_hosts)"
    [ -z "$dst_agent" ] && fail_with "Invalid destination host ($dst), valid ones are: $(list_l3_hosts)"

    [ "$src_agent" = "$dst_agent" ] && fail_with "The source and destination must be different"

    for router in $(list_routers_on_agent $src_agent); do
        if echo "$router" | grep -qf "$file_with_router_ids"; then
            log "moving $router from $src_agent to $dst_agent"
            move_router $router $src_agent $dst_agent
        else
            log "router $router was not specified for migration"
        fi
    done
}


function fail_with() {
    local msg

    msg="$1"

    echo "$msg" >&2
    exit 1
}


function log() {
    local msg

    msg="$1"

    echo "LOG: $msg" >&2
}


function newline_to_space() {
    tr '\n' ' '
}


function list_l3_hosts() {
    neutron agent-list --binary neutron-l3-agent -c host -f value | newline_to_space
}


function l3_agent_of_host() {
    local host

    host="$1"

    neutron agent-list --binary neutron-l3-agent --host $host -c id -f value
}


function list_routers_on_agent() {
    local agent_id

    agent_id="$1"

    neutron router-list-on-l3-agent "$agent_id" -c id -f value
}


function list_router_ports() {
    local router

    router="$1"

    neutron router-port-list $router -c id -f value | newline_to_space
}


function has_port() {
    local host
    local port

    host="$1"
    port="$2"

    local actual_host_and_status
    local actual_status
    local actual_host

    eval $(neutron port-show $port -c status -c binding:host_id -f shell | tr : _)
    actual_host="$binding_host_id"
    actual_status="$status"
    [ "$actual_host" = "$host" ] && [ "$actual_status" = "ACTIVE" ]
}


function move_router() {
    local router
    local src_agent
            local dst_agent

    router="$1"
    src_agent="$2"
    dst_agent="$3"

    local dst_host

    dst_host=$(neutron agent-show $dst_agent -c host -f value)
    [ -n "$dst_host" ]


    ports=$(list_router_ports $router)
    neutron l3-agent-router-remove $src_agent $router
    neutron l3-agent-router-add $dst_agent $router

    echo -n "Waiting for ports to be moved"

    for port in $ports; do
        while ! has_port $dst_host $port; do
            echo -n .
            usleep 100
        done
    done
    echo "done"
}


main "$@"
