"""No real model/network calls: exercise CLI checks before any provider access."""
import asyncio
import pytest

from app.models.budget import PaidBudget
from scripts import run_benchmark_baseline as cli


def test_planned_cost_over_remaining_cap_stops_before_balance_or_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    budget = PaidBudget(tmp_path/'runs/477-paid-budget.json')
    budget.reserve('test_unknown_billing', 4.99)
    monkeypatch.setattr('sys.argv', ['run', '--mode', 'suite', '--repeats', '1',
                                   '--items', 'ITEM_03', '--output', str(tmp_path/'results')])
    class FakeAdapter:
        async def get_balance(self):
            pytest.fail('budget preflight must happen before provider access')
    monkeypatch.setattr(cli, 'get_benchmark_adapter', lambda *a, **k: FakeAdapter())
    with pytest.raises(SystemExit) as error:
        asyncio.run(cli.main())
    assert error.value.code == 2
    assert len(PaidBudget(budget.path).state['requests']) == 1
    assert not (tmp_path/'results').exists()


def test_duplicate_items_rejected_before_budget_or_result_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    monkeypatch.setattr('sys.argv', ['run', '--items', 'ITEM_03', 'ITEM_03',
                                   '--output', str(tmp_path/'results')])
    with pytest.raises(SystemExit) as error:
        asyncio.run(cli.main())
    assert error.value.code == 2
    assert not (tmp_path/'runs/477-paid-budget.json').exists()
    assert not (tmp_path/'results').exists()


def test_lower_output_cap_uses_selected_adapter_bound_without_refunding_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    budget = PaidBudget(tmp_path/'runs/477-paid-budget.json')
    budget.reserve('test_prior_reservations', 4.93283328)
    monkeypatch.setattr('sys.argv', ['run', '--mode', 'vlm', '--repeats', '1',
        '--items', 'ITEM_04', '--vlm-transport', 'deepseek_json_labels_v3',
        '--output', str(tmp_path/'results')])
    class MockBalanceBoundaryReached(Exception):
        pass
    class FakeAdapter:
        reservation_upper_usd = .058752
        async def get_balance(self):
            raise MockBalanceBoundaryReached
    options = {}
    def mock_factory(name, **kwargs):
        options[name] = kwargs
        return FakeAdapter()
    monkeypatch.setattr(cli, 'get_benchmark_adapter', mock_factory)
    with pytest.raises(MockBalanceBoundaryReached):
        asyncio.run(cli.main())
    assert options['general_vlm']['transport_profile'] == 'deepseek_json_labels_v3'
    assert len(PaidBudget(budget.path).state['requests']) == 1
    assert float(PaidBudget(budget.path).reserved_usd) == 4.93283328


def test_missing_provider_usage_reports_known_part_without_claiming_total(tmp_path):
    budget = PaidBudget(tmp_path/'budget.json')
    first = budget.reserve('test_known', .5)
    budget.settle(first, {'input_tokens': 100}, .05, 'response_received')
    budget.reserve('test_unknown', .5)
    status = cli.public_budget_status(budget)
    assert status['usage_cost_estimate_usd'] is None
    assert status['known_partial_usage_cost_estimate_usd'] == .05
    assert status['requests'] == 2
    assert status['usage_cost_known_requests'] == 1
    assert status['actual_invoice_cost_usd'] is None
