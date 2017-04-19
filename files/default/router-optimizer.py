import logging
import argparse
import importlib
import textwrap
from logging.handlers import SysLogHandler

LOG = logging.getLogger('router-optimizer')
LOG_FORMAT = '%(asctime)s %(name)-12s %(levelname)-8s %(message)s'
LOG_DATE = '%m-%d %H:%M'

# Try to fall back loading the neutron-ha-tool from an absolute path.
# As on the installed system we're installing neutron-ha-tool without
# the ".py" extension, which causes importlib.import_module to fail.
try:
    hatool = importlib.import_module("neutron-ha-tool")
except ImportError:
    import imp
    import os
    dirname = os.path.dirname(os.path.abspath(__file__))
    hatool = imp.load_source(
        '', os.path.join(dirname, '/usr/bin/neutron-ha-tool'))


class Router(object):
    def __init__(self, router_dict, agent):
        self.router_dict = router_dict
        self.agent = agent
        self.availability_zones = set()

    @property
    def id(self):
        return self.router_dict['id']

    def __str__(self):
        return self.id


def network_ids_for_router(neutron_client, router_id):
    ports = neutron_client.list_ports(
        device_id=router_id,
        device_owner='network:router_interface'
    )['ports']

    return sorted(set(port['network_id'] for port in ports))


def compute_azs_connected_to(neutron_client, network_id):
    ports = neutron_client.list_ports(
        network_id=network_id,
    )['ports']

    return sorted(set(
        port['device_owner'][len('compute:'):] for port in ports
        if port['device_owner'].startswith('compute:')
    ))


class RouterLayout(object):
    def __init__(self):
        self.agents = []
        self.routers = []

    def add_agent(self, agent):
        self.agents.append(agent)

    def add_router(self, router):
        self.routers.append(router)

    def find_agents_for_az(self, az):
        return set(
            agent for agent in self.agents if agent.availability_zone == az
        )

    def find_agent_for(self, availability_zones):
        candidate_agents = set()
        for az in availability_zones:
            for agent in self.find_agents_for_az(az):
                candidate_agents.add(agent)

        if len(candidate_agents) == 1:
            return candidate_agents.pop()

        if len(candidate_agents) > 1:
            LOG.warn('Multiple agents found for availability zones %s',
                     availability_zones)

        return None


def discover_router_layout(neutron_client):
    router_layout = RouterLayout()

    live_agent_list = hatool.live_agent_list(neutron_client)

    for agent in live_agent_list.agents:
        router_layout.add_agent(agent)
        for router_dict in agent.routers:
            router = Router(router_dict, agent)

            azs_for_router = set()
            for network_id in network_ids_for_router(neutron_client, router.id):
                for az in compute_azs_connected_to(neutron_client, network_id):
                    azs_for_router.add(az)

            router.availability_zones = azs_for_router
            router_layout.add_router(router)

    return router_layout


def parse_args():
    ap = argparse.ArgumentParser(description=textwrap.dedent("""
    Router optimizer
    
    This script assumes that L3 agents's description field refers to an
    availability zone that is closest to the agent. The script queries all
    routers of the live agents, and gathers all the networks the router is
    connected to. From the list of networks per router it finds out what
    availabilty zones serve instances connected to those networks.
    
    If a router is living in a different AZ then what the router's connected
    instances suggest, the script suggests a move of the router to one of
    the agents that is living on the AZ.
    """))
    ap.add_argument('-d', '--debug', action='store_true',
                    default=False, help='Show debugging output')
    ap.add_argument('-q', '--quiet', action='store_true', default=False,
                    help='Only show error and warning messages')
    ap.add_argument('--insecure', action='store_true', default=False,
                    help='Explicitly allow tool to perform '
                         '"insecure" SSL (https) requests. The server\'s '
                         'certificate will not be verified against any '
                         'certificate authorities. This option should be used '
                         'with caution.')
    return ap.parse_args()


def setup_logging(args):
    level = logging.INFO
    if args.quiet:
        level = logging.WARN
    if args.debug:
        level = logging.DEBUG
    logging.basicConfig(level=level, format=LOG_FORMAT, date_fmt=LOG_DATE)
    handler = SysLogHandler(address='/dev/log')
    syslog_formatter = logging.Formatter('%(name)s: %(levelname)s %(message)s')
    handler.setFormatter(syslog_formatter)
    LOG.addHandler(handler)


def main():
    args = parse_args()
    setup_logging(args)
    neutron_client = hatool.neutron_client(insecure=args.insecure)
    router_layout = discover_router_layout(neutron_client)

    for router in router_layout.routers:
        if router.agent.availability_zone:
            LOG.info(
                'Router %s living on agent %s, routing traffic for '
                'availability zone(s): %s',
                router, router.agent, ', '.join(router.availability_zones)
            )
            if router.agent.availability_zone in router.availability_zones:
                LOG.info('Router %s needs no move', router)
            else:
                target_agent = router_layout.find_agent_for(
                    router.availability_zones
                )
                if target_agent is None:
                    LOG.warning(
                        'Could not find a new agent for router %s', router
                    )
                else:
                    LOG.info(
                        'Router %s needs to be moved to %s',
                        router, target_agent
                    )
        else:
            LOG.warning(
                'Agent %s hosting router %s has no availability zone '
                'associated', router.agent
            )


if __name__ == "__main__":
    main()
