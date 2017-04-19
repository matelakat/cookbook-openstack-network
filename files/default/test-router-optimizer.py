import unittest
import importlib

router_optimizer = importlib.import_module("router-optimizer")
ha_tool = importlib.import_module("neutron-ha-tool")
tests = importlib.import_module("test-neutron-ha-tool")


def make_neutron_client(live_agents=None):
    fake_neutron = tests.FakeNeutron()
    for live_agent in live_agents or []:
        fake_neutron.add_live_l3_agent(live_agent)

    return tests.FakeNeutronClient(fake_neutron)


class TestDiscoverRouterLayout(unittest.TestCase):
    def test_empty_neutron_database(self):
        layout = router_optimizer.discover_router_layout(
            make_neutron_client()
        )

        self.assertEqual(0, len(layout.agents))
        self.assertEqual(0, len(layout.routers))

    def test_agent_with_no_description_yields_none_az(self):
        layout = router_optimizer.discover_router_layout(
            make_neutron_client(live_agents=['agent-A'])
        )

        agent, = layout.agents
        self.assertIsNone(agent.availability_zone)

    def test_agent_with_no_description_sets_az(self):
        fake_neutron = tests.FakeNeutron()
        fake_neutron.add_live_l3_agent('agent-A', description='some-az')
        neutron_client = tests.FakeNeutronClient(fake_neutron)

        layout = router_optimizer.discover_router_layout(
            neutron_client
        )

        self.assertEqual(1, len(layout.agents))
        agent = layout.agents[0]

        self.assertEqual('agent-A', agent.id)
        self.assertEqual('some-az', agent.availability_zone)

    def test_routers_listed(self):
        fake_neutron = tests.FakeNeutron()
        fake_neutron.add_live_l3_agent('agent-A')
        fake_neutron.add_router('agent-A', 'router-A', {})
        neutron_client = tests.FakeNeutronClient(fake_neutron)

        layout = router_optimizer.discover_router_layout(
            neutron_client
        )

        self.assertEqual(1, len(layout.routers))
        router = layout.routers[0]

        self.assertEqual('router-A', router.id)
        self.assertEqual('agent-A', router.agent.id)

    def test_routers_know_their_availibility_zone(self):
        fake_neutron = tests.FakeNeutron()
        fake_neutron.add_live_l3_agent('agent-A')
        fake_neutron.add_router('agent-A', 'router-A', {})
        fake_neutron.add_port(
            'port-1',
            device_id='router-A',
            device_owner='network:router_interface',
            network_id='network-1'
        )
        fake_neutron.add_port(
            'port-2',
            network_id='network-1',
            device_owner='compute:az-A'
        )
        neutron_client = tests.FakeNeutronClient(fake_neutron)

        layout = router_optimizer.discover_router_layout(
            neutron_client
        )

        self.assertEqual(1, len(layout.routers))
        router = layout.routers[0]

        self.assertEqual('router-A', router.id)
        self.assertEqual('agent-A', router.agent.id)
        self.assertIn('az-A', router.availability_zones)


class TestRouterLayout(unittest.TestCase):
    def test_find_agents_for_az_returns_empty_if_router_has_no_az(self):
        router_layout = router_optimizer.RouterLayout()
        router_layout.add_agent(ha_tool.Agent({}, []))

        self.assertSetEqual(set(), router_layout.find_agents_for_az('blah'))

    def test_find_agents_for_az_returns_multiple_matches(self):
        router_layout = router_optimizer.RouterLayout()
        agent_1 = ha_tool.Agent({'description': 'az1'}, [])
        agent_2 = ha_tool.Agent({'description': 'az2'}, [])
        agent_3 = ha_tool.Agent({}, [])
        router_layout.add_agent(agent_1)
        router_layout.add_agent(agent_2)
        router_layout.add_agent(agent_3)

        self.assertSetEqual(
            set([agent_1]),
            router_layout.find_agents_for_az('az1')
        )

    def test_find_agent_for_without_no_agents(self):
        router_layout = router_optimizer.RouterLayout()

        self.assertIsNone(router_layout.find_agent_for(['az1']))

    def test_find_agent_for_returns_matching_agent(self):
        router_layout = router_optimizer.RouterLayout()
        agent_1 = ha_tool.Agent({'description': 'az1'}, [])
        router_layout.add_agent(agent_1)

        self.assertEqual(agent_1, router_layout.find_agent_for(['az1']))

    def test_find_agent_for_returns_none_if_multiple_matches(self):
        router_layout = router_optimizer.RouterLayout()
        agent_1 = ha_tool.Agent({'description': 'az1'}, [])
        agent_2 = ha_tool.Agent({'description': 'az1'}, [])
        router_layout.add_agent(agent_1)
        router_layout.add_agent(agent_2)

        self.assertIsNone(router_layout.find_agent_for(['az1']))


class TestRouter(unittest.TestCase):
    def test_str(self):
        router = router_optimizer.Router({'id': 'some-router'}, None)

        self.assertEqual('some-router', str(router))
