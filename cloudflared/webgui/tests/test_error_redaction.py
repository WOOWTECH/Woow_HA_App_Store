"""Response diagnostics must not echo submitted secrets."""
import asyncio
import base64
import json
import pytest
from backend.instances import supervisor
from backend.supervisor import SupervisorClient, SupervisorError
MARKER = 'HA05_SYNTHETIC_PRIVATE_ERROR_MARKER'
TOKEN = base64.b64encode(json.dumps({'a':'synthetic','t':'synthetic','s':MARKER}).encode()).decode()
def assert_clean(response, status):
    assert response.status_code == status
    assert MARKER not in response.text
    assert TOKEN not in response.text
@pytest.mark.parametrize('payload', [
    {'tunnel_token':MARKER},
    {'tunnel_token':TOKEN,'catch_all_service':'http://example.invalid','nginx_proxy_manager':True},
    {'tunnel_token':TOKEN,'external_hostname':'https://'+MARKER},
    {'tunnel_token':TOKEN,'run_parameters':['--not-allowed='+MARKER]},
])
def test_validation_errors_exclude_input_values(client, fake_supervisor, payload):
    before=dict(fake_supervisor.options)
    response=client.put('/api/options',json=payload)
    assert_clean(response,422)
    for error in response.json()['detail']:
        assert set(error)=={'loc','type','msg'}
    assert fake_supervisor.options==before
@pytest.mark.parametrize('method', ['get','put'])
def test_supervisor_errors_keep_status_not_upstream_prose(client, monkeypatch, method):
    async def reject(*args,**kwargs):
        raise SupervisorError(MARKER+' '+TOKEN,400)
    monkeypatch.setattr(supervisor,'get_options' if method=='get' else 'set_options',reject)
    response=client.get('/api/options') if method=='get' else client.put('/api/options',json={'external_hostname':'ha.example.invalid'})
    assert_clean(response,400)
    assert response.json()['detail']
def test_restart_health_does_not_expose_upstream_prose(client,monkeypatch):
    async def reject(*args,**kwargs):
        raise SupervisorError(MARKER+' '+TOKEN,400)
    monkeypatch.setattr(supervisor,'_request',reject)
    monkeypatch.setattr(supervisor,'last_restart_error',None)
    asyncio.run(SupervisorClient.restart_self(supervisor))
    response=client.get('/api/health')
    assert_clean(response,200)
    assert response.json()['restart_error']
