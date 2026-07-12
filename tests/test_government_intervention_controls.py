# -*- coding: utf-8 -*-
"""Focused control tests for independent interventions and dynamic opinion."""
from types import SimpleNamespace

from core.agents import GovernmentAgent
from core.event_influence import EventInfluenceCalculator


class _Enterprise:
    def __init__(self):
        self.zone = 'z0'
        self.enterprise_type = 'small'
        self.desperation_level = 0.6
        self.current_request_intensity = 0.8
        self.is_in_crisis = True
        self.loss = 10.0
        self.compensation = []

    def request(self):
        return self.current_request_intensity

    def receive_compensation(self, amount):
        self.compensation.append(amount)
        self.loss = max(0.0, self.loss - amount)


def test_manual_on_for_one_event_keeps_other_events_automatic():
    gov = GovernmentAgent()
    # Legacy UI behaviour: only Event 5 is manually switched on.
    gov.use_manual_events = True
    gov.manual_public_opinion = True

    gov.decide(0.0, 0.0, 0.0, 0.0, {}, outage_ratio=0.5)

    assert gov.public_opinion_active is True
    assert gov.emergency_warning_issued is True
    assert gov.resource_to_grid is True

    # Explicit OFF has local scope; it does not disable warning/grid auto mode.
    gov.set_event_mode('public_opinion', 'off')
    gov.decide(0.0, 0.0, 0.0, 0.0, {}, outage_ratio=0.5)
    assert gov.public_opinion_active is False
    assert gov.emergency_warning_issued is True
    assert gov.resource_to_grid is True


def test_manual_resource_to_enterprise_runs_compensation_route():
    gov = GovernmentAgent()
    enterprise = _Enterprise()
    gov.set_event_mode('resource_to_enterprise', 'on')

    gov.allocate_resources([enterprise], 10.0, {'z0': 0.5}, [])

    assert gov.resource_to_enterprise is True
    assert gov.last_resource_to_enterprise_amount > 0.0
    assert sum(enterprise.compensation) == gov.last_resource_to_enterprise_amount
    assert enterprise.loss < 10.0

    gov.set_event_mode('resource_to_enterprise', 'off')
    prior_count = len(enterprise.compensation)
    gov.allocate_resources([enterprise], 10.0, {'z0': 0.5}, [])
    assert gov.resource_to_enterprise is False
    assert gov.last_resource_to_enterprise_amount == 0.0
    assert len(enterprise.compensation) == prior_count


def test_public_opinion_state_decays_and_management_relief_is_exported():
    calculator = EventInfluenceCalculator()
    resident = SimpleNamespace(
        emotion=0.5,
        panic_value=0.5,
        rumor_belief=0.5,
        info_received={'official': 0.0},
        state='S',
    )
    management_effect = calculator.calc_opinion_management_effect(
        True, [resident], dt=0.5, total_residents=1
    )
    assert management_effect['opinion_pressure_relief'] > 0.0

    calculator.public_opinion_pressure = 0.6
    effects = {
        'summary': {
            'total_gov_pressure': 0.0,
            'total_opinion_pressure': 0.0,
            'opinion_management_pressure_relief': management_effect['opinion_pressure_relief'],
        }
    }

    calculator._update_pressure_indices(effects, dt=0.5)

    assert 0.0 <= calculator.public_opinion_pressure < 0.6
    assert calculator.opinion_pressure == calculator.public_opinion_pressure
    assert effects['summary']['opinion_pressure_decay'] > 0.0
    assert effects['summary']['opinion_pressure_net_change'] < 0.0
    assert effects['summary']['public_opinion_pressure'] == calculator.public_opinion_pressure


def test_event_context_ignores_inactive_resource_amounts():
    calculator = EventInfluenceCalculator()
    sim = SimpleNamespace(
        gov_agents={
            'active': SimpleNamespace(resource_to_grid=True, last_resource_to_grid_amount=2.5),
            'inactive': SimpleNamespace(resource_to_grid=False, last_resource_to_grid_amount=99.0),
        }
    )

    active, amount = calculator._government_event_context(
        sim, 'resource_grid', 'last_resource_to_grid_amount'
    )

    assert active is True
    assert amount == 2.5
