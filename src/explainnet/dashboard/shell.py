"""Shared read-only status shell for every route and fragment rerun."""
import os
from datetime import UTC, datetime

import streamlit as st

from explainnet.dashboard.presentation import measurement_window, telemetry_freshness, value


def status_panel(client, status, read):
    config = read(client, '/v1/config')
    identity = (config or {}).get('identity', {})
    expected = os.environ.get('EXPLAINNET_CONFIG_HASH')
    if expected and (config or {}).get('config_hash') != expected:
        st.error('Configuration identity mismatch. Stop and launch the selected profile again.')
        return False
    st.markdown('**Profile: ' + identity.get('profile', 'Unavailable') + '**')
    if not status:
        st.error('API unavailable. Refresh later or inspect the launcher status.')
        st.caption('Last successful read: ' + st.session_state.get('last_successful_read', 'Unavailable'))
        st.caption('Selected network: '+st.session_state.get('selected_original','Unavailable'))
        st.caption('Agent / collector / expiry / observation age: unavailable')
        st.caption('Operating mode: unavailable; no mutation enabled')
        return True
    st.session_state['last_successful_read'] = status['at_utc']
    st.caption('Last successful read: ' + status['at_utc'][11:19]+' UTC')
    st.caption('API: connected | Agent: ' + ('ready' if status['agent']['available'] else 'unavailable'))
    control = status['control']
    st.caption('Mode: ' + control['mode'] + ' | Automatic repair: ' + ('ON' if control['auto_enabled'] else 'OFF'))
    if control.get('unsettled_action_ids'):
        st.error('Interrupted action requires explicit reconciliation: ' + ', '.join(control['unsettled_action_ids']))
    if control.get('cleanup_pending_workflow_ids'):
        st.error('Owned twin cleanup pending: ' + ', '.join(control['cleanup_pending_workflow_ids']))
    originals = [r['instance_id'] for r in status['agent']['instances']
        if r.get('role') == 'original' and r.get('state') == 'running' and r.get('live_verified')]
    if originals:
        saved = st.session_state.get('selected_original')
        if saved not in originals:
            st.session_state['selected_original'] = originals[0]
        original = st.selectbox('Selected original network', originals, key='selected_original')
        data = read(client, '/v1/dashboard/telemetry/' + original + '?limit=60') or {}
        collector = data.get('collector', {})
        window = measurement_window(collector, data.get('windows', []))
        st.caption('Observation: ' + ((window or {}).get('at_utc') or 'Unavailable'))
        try:age=(datetime.now(UTC)-datetime.fromisoformat(window['at_utc'])).total_seconds()
        except (TypeError,KeyError,ValueError):age=None
        st.caption('Observation age: '+value(age,'s',0))
        st.caption('Measurements: ' + telemetry_freshness(collector, window))
        st.caption('Collector: ' + ('running' if collector.get('live') else 'stopped / unavailable'))
        st.caption('Collector expiry (UTC): ' + (collector.get('expires_utc') or 'Unavailable'))
        st.caption('Collector remaining: ' + value(collector.get('remaining_s'), 's', 0))
    else:
        st.caption('Selected original network: unavailable')
        st.caption('Observation: unavailable | Measurements: unavailable')
        st.caption('Collector: unavailable | Expiry / remaining: unavailable')
    with st.expander('Technical configuration'):
        st.caption(identity.get('diagnosis_contract','Backend identity unavailable; verify the selected configuration.'))
        st.caption('Full successful read UTC: '+status['at_utc'])
        st.json(identity)
        st.caption('Active model: ' + (status['models'].get('active_model_id') or 'None'))
    return True
