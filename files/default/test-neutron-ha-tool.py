import datetime
import unittest
import collections
ha_tool = __import__("neutron-ha-tool")


class MockNeutronClient(object):

    def __init__(self):
        self.routers = {}
        self.agents = {}
        self.routers_by_agent = collections.defaultdict(set)

    def tst_add_agent(self, agent_id, props):
        self.agents[agent_id] = dict(props, id=agent_id)

    def tst_add_router(self, agent_id, router_id, props):
        self.routers[router_id] = dict(props, id=router_id)
        self.routers_by_agent[agent_id].add(router_id)

    def tst_agent_by_router(self, router_id):
        for agent_id, router_ids in self.routers_by_agent.items():
            if router_id in router_ids:
                return self.agents[agent_id]

        raise NotImplementedError()

    def list_agents(self):
        return {
            'agents': self.agents.values()
        }

    def list_routers_on_l3_agent(self, agent_id):
        return {
            'routers': [
                self.routers[router_id]
                for router_id in self.routers_by_agent[agent_id]
            ]
        }

    def remove_router_from_l3_agent(self, agent_id, router_id):
        self.routers_by_agent[agent_id].remove(router_id)

    def add_router_to_l3_agent(self, agent_id, router_body):
        self.routers_by_agent[agent_id].add(router_body['router_id'])

    def list_ports(self, device_id, fields):
        return {
            'ports': [
                {
                    'id': 'someid',
                    'binding:host_id':
                        self.tst_agent_by_router(device_id)['host'],
                    'binding:vif_type': 'non distributed',
                    'status': 'ACTIVE'
                }
            ]
        }

    def list_floatingips(self, router_id):
        return {
            'floatingips': [
                {
                    'id': 'irrelevant',
                    'status': 'ACTIVE'
                }
            ]
        }


class TestL3AgentMigrate(unittest.TestCase):

    def setUp(self):
        import logging
        logging.basicConfig(level=logging.DEBUG)

    def test_no_agents_returns_zero(self):
        neutron_client = MockNeutronClient()
        result = ha_tool.l3_agent_migrate(neutron_client)

        self.assertEqual(0, result)

    def test_no_alive_agents_returns_one(self):
        neutron_client = MockNeutronClient()
        neutron_client.tst_add_agent(
            'agent-1', {
                'agent_type': 'L3 agent',
                'alive': False,
                'admin_state_up': True,
                'host': 'host1'
            }
        )
        result = ha_tool.l3_agent_migrate(neutron_client)

        self.assertEqual(1, result)

    def test_router_moved(self):
        neutron_client = MockNeutronClient()
        neutron_client.tst_add_agent(
            'agent-1', {
                'agent_type': 'L3 agent',
                'alive': True,
                'admin_state_up': True,
                'host': 'host1'
            }
        )
        neutron_client.tst_add_agent(
            'agent-2', {
                'agent_type': 'L3 agent',
                'alive': False,
                'admin_state_up': True,
                'host': 'host2'
            }
        )
        neutron_client.tst_add_router('agent-2', 'router-1', {})
        result = ha_tool.l3_agent_migrate(neutron_client, now=True)

        self.assertEqual(0, result)
        self.assertEqual(
            set(['router-1']), neutron_client.routers_by_agent['agent-1'])


class TestL3AgentEvacuate(unittest.TestCase):

    def setUp(self):
        import logging
        logging.basicConfig(level=logging.DEBUG)

    def test_no_agents_returns_zero(self):
        neutron_client = MockNeutronClient()
        result = ha_tool.l3_agent_evacuate(neutron_client, 'host1')

        self.assertEqual(0, result)

    def test_evacuation(self):
        neutron_client = MockNeutronClient()
        neutron_client.tst_add_agent(
            'agent-1', {
                'agent_type': 'L3 agent',
                'alive': True,
                'admin_state_up': True,
                'host': 'host1',
                'configurations': {
                    'agent_mode': 'Mode X'
                }
            }
        )
        neutron_client.tst_add_agent(
            'agent-2', {
                'agent_type': 'L3 agent',
                'alive': True,
                'admin_state_up': True,
                'host': 'host2',
                'configurations': {
                    'agent_mode': 'Mode X'
                }
            }
        )
        neutron_client.tst_add_router('agent-2', 'router-1', {})

        result = ha_tool.l3_agent_evacuate(neutron_client, 'host2')

        self.assertEqual(0, result)
        self.assertEqual(
            set(['router-1']), neutron_client.routers_by_agent['agent-1'])


class TestLeastBusyAgentPicker(unittest.TestCase):

    def setUp(self):
        import logging
        logging.basicConfig(level=logging.DEBUG)
        neutron_client = MockNeutronClient()
        neutron_client.tst_add_agent(
            'agent-1', {
                'agent_type': 'L3 agent',
                'alive': True,
                'admin_state_up': True,
                'host': 'host1',
                'configurations': {
                    'agent_mode': 'Mode X'
                }
            }
        )
        neutron_client.tst_add_agent(
            'agent-2', {
                'agent_type': 'L3 agent',
                'alive': True,
                'admin_state_up': True,
                'host': 'host2',
                'configurations': {
                    'agent_mode': 'Mode X'
                }
            }
        )
        neutron_client.tst_add_router('agent-1', 'router-1', {})
        self.neutron_client = neutron_client

    def make_picker(self):
        return ha_tool.LeastBusyAgentPicker(
            self.neutron_client,
            [
                {'id': 'agent-1'},
                {'id': 'agent-2'}
            ]
        )

    def test_initial_numbers_queried(self):
        picker = self.make_picker()
        self.assertEqual(
            {
                'agent-1': 1,
                'agent-2': 0
            },
            picker.router_count_per_agent_id
        )

    def test_least_busy_picked(self):
        picker = self.make_picker()

        self.assertEqual('agent-2', picker.pick()['id'])

    def test_router_counts_maintained(self):
        picker = self.make_picker()

        picker.pick()

        self.assertEqual(
            {
                'agent-1': 1,
                'agent-2': 1
            },
            picker.router_count_per_agent_id
        )

    def test_routers_picked_evenly(self):
        picker = self.make_picker()

        self.assertEqual('agent-2', picker.pick()['id'])
        self.assertEqual('agent-1', picker.pick()['id'])
        self.assertEqual('agent-2', picker.pick()['id'])

    def test_cache_reloaded(self):
        picker = self.make_picker()

        self.neutron_client.tst_add_router('agent-2', 'router-2', {})
        self.neutron_client.tst_add_router('agent-2', 'router-3', {})

        picker.cache_created_at = (
            picker.cache_created_at - datetime.timedelta(
                seconds=ha_tool.ROUTER_CACHE_MAX_AGE_SECONDS + 1)
        )

        self.assertEqual('agent-1', picker.pick()['id'])

    def test_pick_on_empty_array_throws_index_error_as_random_does(self):
        picker = ha_tool.LeastBusyAgentPicker(self.neutron_client, [])

        with self.assertRaises(IndexError):
            picker.pick()


if __name__ == "__main__":
    unittest.main()
