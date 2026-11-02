"""Six evidence-led pages. All reads and intentional mutations go through HTTP."""
import html
import json
from datetime import UTC, datetime
from itertools import pairwise
from uuid import uuid4

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from explainnet.dashboard.client import ApiClient, ApiError
from explainnet.dashboard.presentation import (
    candidate_rows,
    measurement_window,
    readiness,
    retry_intent,
    send_intent,
    telemetry_freshness,
    value,
)
from explainnet.dashboard_api import DashboardStatus, Records, public_value
from explainnet.workflow_contracts import WorkflowRequest

NAVY, TEAL, MUTED = '#142D4E', '#087F8C', '#63748A'
MODES = {'observe': 'Observe', 'recommend': 'Recommend', 'assisted-repair': 'Assisted Repair', 'lab-auto-repair': 'Lab Auto-Repair'}
PAGES = ['Overview', 'Network & Telemetry', 'Incidents & Diagnosis', 'Digital Twin & Recommendations', 'Recovery & Audit', 'Evidence & Project Information']


def read(client, path, model=None):
    try:
        return client.get(path, model)
    except ApiError as exc:
        st.warning(str(exc), icon='⚠️')
        if exc.request_id:
            st.caption('Support request: ' + exc.request_id)
        return None


def records(client, name):
    return (read(client, '/v1/dashboard/records/' + name, Records) or {}).get('records', [])


def raw(label, data):
    with st.expander(label):
        st.json(public_value(data))


def empty(title, description):
    with st.container(border=True):
        st.markdown('#### ' + title)
        st.caption(description)


def table(rows):
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')


def badge(label, text):
    st.markdown(f'<div class="status-card"><span>{html.escape(label)}</span><strong>{html.escape(str(text))}</strong></div>', unsafe_allow_html=True)


def card_row(items):
    for column, (label, text) in zip(st.columns(len(items)), items, strict=True):
        with column:
            badge(label, text)


def choose(rows, key, field, label):
    if not rows:
        return None
    selected = st.selectbox(label, [r[field] for r in rows], key=key)
    return next(r for r in rows if r[field] == selected)


def mutation(client, slot, label, path, payload, confirmations=None, disabled=False, direct=False):
    """Called only inside an intentional form; latch before I/O."""
    intents = st.session_state.setdefault('intents', {})
    prior = intents.get(slot)
    clicked = st.form_submit_button(label, type='primary', disabled=disabled or prior is not None)
    if clicked:
        try:
            result = send_intent(client, intents, slot, path, payload, confirmations or [True], direct)
            if result['state'] == 'acknowledged':
                st.success('Request accepted. Follow its actual outcome in Request activity.')
            else:
                st.warning(result.get('error', 'Request state is unknown. Check the receipt.'))
        except (ValueError, TypeError) as exc:
            st.error(str(exc))
    if prior:
        st.caption(f"Request {prior['key']} • {prior['state']}. Review activity before preparing another request.")
    return clicked


def activity(client):
    intents = st.session_state.get('intents', {})
    if not intents:
        return
    with st.expander('Request activity', expanded=True):
        for slot, receipt in list(intents.items())[-20:]:
            job = None
            if receipt.get('job_id'):
                job = receipt.get('terminal_job') or read(client, '/v1/jobs/' + receipt['job_id'])
                if job:
                    unknown_outcome = bool((job.get('result') or {}).get('requires_reconciliation'))
                    if job['state'] in {'succeeded', 'failed', 'canceled', 'interrupted'}:
                        receipt['terminal_job'] = job
                    st.markdown(f"**{slot.replace('_', ' ').title()}** — submission job: {job['state']}")
                    if receipt['path'] in {'/v1/lab/workflow', '/v1/lab/apply', '/v1/lab/automation/start'}:
                        st.caption('This is request acceptance, not repair verification. Follow the current workflow and action on Recovery & Audit.')
                    if job.get('error'):
                        st.error(public_value(job['error']))
                    if unknown_outcome:
                        st.warning('Mutation outcome is unknown. Read back the selected owned network and explicitly reconcile through /v1/laboratory/reconcile before preparing another intent. Do not repeat the mutation.')
                        instance = receipt.get('payload', {}).get('instance_id')
                        if instance and not receipt.get('reconciliation_job') and st.button('Reconcile owned state', key='reconcile_' + slot):
                            try:
                                reconciled = client.submit('/v1/laboratory/reconcile', {'instance_id': instance}, receipt['key'] + '_reconcile')
                                receipt['reconciliation_job'] = reconciled['job_id']
                            except ApiError as exc:
                                st.warning(str(exc))
                        if receipt.get('reconciliation_job'):
                            reconciled = read(client, '/v1/jobs/' + receipt['reconciliation_job'])
                            if reconciled and reconciled['state'] == 'succeeded':
                                receipt['outcome_reconciled'] = True
                                st.info('Owner read-back complete. Review actual runs below before preparing a new intent. The original failed job is retained.')
                                raw('Owned state after reconciliation', reconciled['result'])
                    raw('Job receipt · ' + receipt['job_id'], job)
            elif receipt['state'] == 'unknown':
                st.warning(receipt['error'])
                if st.button('Check submission receipt', key='check_' + slot):
                    result = read(client, '/v1/dashboard/submissions/' + receipt['key'])
                    if result and result['found']:
                        receipt.update(job_id=result['job_id'], state='acknowledged')
                    elif result:
                        st.info('No receipt found yet. No mutation has been retried.')
                if st.button('Retry original request with the same key', key='retry_' + slot):
                    retry_intent(client, receipt)
                    st.rerun()
            else:
                st.caption(slot + ': ' + receipt['state'])
                if receipt.get('error'):
                    st.error(receipt['error'])
            terminal = job and job['state'] in {'succeeded', 'failed', 'canceled', 'interrupted'} and (
                not (job.get('result') or {}).get('requires_reconciliation') or receipt.get('outcome_reconciled'))
            resettable = terminal or receipt['state'] == 'rejected' or (receipt['state'] == 'acknowledged' and not receipt.get('job_id'))
            if resettable and st.button('Prepare another request', key='new_' + slot):
                del intents[slot]
                fields = {'workflow_start': ('workflow_suffix', 'workflow_key'), 'automation_start': ('workflow_suffix', 'workflow_key'),
                    'v4_workflow':('v4_workflow_suffix',),'v4_monitor':('v4_workflow_suffix',),
                    'v4_apply':('v4_action_suffix',),'v4_undo':('v4_undo_suffix',),'guided_create':('guided_instance',),
                    'assisted_apply': ('apply_suffix', 'confirm_apply_' + receipt['payload'].get('workflow_id', '')),
                    'mode_change': ('confirm_auto', 'confirm_observed'),
                    'network_teardown': ('confirm_teardown_' + receipt['payload'].get('instance_id', ''),),
                    'undo': ('undo_suffix', 'confirm_undo_' + receipt['payload'].get('instance_id', ''))}.get(slot, ())
                for field in fields:
                    st.session_state.pop(field, None)
                st.rerun()


def live_networks(status):
    return [r for r in status['agent']['instances'] if r.get('state') == 'running' and r.get('live_verified') and r.get('role') == 'original']


def select_network(status):
    networks = live_networks(status)
    if not networks:
        empty('No verified active original network', 'Start an owned laboratory from Network & Telemetry. Saved networks are not treated as live.')
        return None
    selected = st.session_state.get('selected_original')
    if selected in [r['instance_id'] for r in networks]:
        st.caption('Original laboratory: ' + selected)
        return selected
    return st.selectbox('Original laboratory', [r['instance_id'] for r in networks], key='original_network')


def overview(client, status):
    st.markdown('<div class="eyebrow">NETWORK OPERATIONS LAB</div>', unsafe_allow_html=True)
    st.title('ExplainNet Twin')
    st.markdown('### Automated Network Diagnosis and Repair using a Digital Twin')
    st.caption('Observe service → investigate evidence → test a separate twin → apply an eligible repair → verify or roll back.')
    if status is None:
        for c, item in zip(st.columns(5), readiness(None), strict=True):
            with c:
                badge(*item)
        empty('Connect the backend to begin', 'The dashboard can render without a network. Start the unprivileged API and use its loopback URL in the launcher.')
        return
    networks = live_networks(status)
    mode = MODES[status['control']['mode']]
    card_row([('API', '✓ Connected'), ('Privileged agent', '✓ Connected' if status['agent']['available'] else '○ Unavailable'),
        ('Verified active originals', str(len(networks)) if status['agent']['available'] else 'Unknown'), ('Operating mode', mode)])
    st.subheader('Readiness, one prerequisite at a time')
    card_row(readiness(status)[1:])
    left, right = st.columns([1.4, 1])
    fresh_telemetry = False
    with left:
        st.subheader('Current laboratory')
        if networks:
            table([{k: r.get(k) for k in ('instance_id', 'state', 'forwarding_version')} for r in networks])
            telemetry = read(client, f"/v1/dashboard/telemetry/{networks[0]['instance_id']}?limit=4")
            if telemetry:
                windows = telemetry.get('windows', [])
                freshness = telemetry_freshness(telemetry['collector'], measurement_window(telemetry['collector'], windows))
                fresh_telemetry = freshness == 'Fresh'
                badge('Telemetry', freshness)
        else:
            empty('No live network', 'Historical experiment reports remain available under Evidence & Project Information.')
        st.subheader('Latest recorded activity')
        for name, field, title in [('incidents', 'incident_id', 'Incident'), ('experiments', 'operation_id', 'Recommendation experiment'), ('actions', 'action_id', 'Recovery outcome')]:
            rows = records(client, name)
            if rows:
                r = rows[0]
                st.markdown(f"**{title}:** `{r[field]}` · {r['state']}")
            else:
                st.caption(title + ': no records in the connected backend.')
    with right:
        with st.container(border=True):
            st.markdown('#### Demonstration checklist')
            for line in ['✓ Local dashboard and typed backend interfaces',
                    ('✓' if status['agent']['available'] else '○') + ' Privileged agent connection',
                    ('✓' if fresh_telemetry else '○') + ' Verified original network and fresh telemetry',
                    ('✓' if status['dataset']['ready'] else '○') + ' Completed and quality-qualified main dataset',
                    ('✓' if status['models']['active_model_id'] else '○') + ' Activated compatible trained model',
                    ('✓' if status['explanations']['ready_count'] else '○') + ' Real model/window SHAP results']:
                st.write(line)
            st.caption('API connectivity alone does not establish any other prerequisite.')
        st.info('Historical repair coverage is conditional UDP latency. Other faults require their own passing evidence.')


def topology_figure(definition, selected):
    graph = nx.Graph()
    switches = definition.get('switches', [])
    graph.add_nodes_from(switches)
    hosts = definition.get('hosts', [])
    for h in hosts:
        graph.add_edge(h['host_id'], h['switch_id'], label='Access capacity ' + value(h.get('access_bps'), 'bps', 0))
    for link in definition.get('links', []):
        graph.add_edge(link['source'], link['target'], label='Forward capacity ' + value(link.get('forward_bps'), 'bps', 0)
            + ' · Reverse capacity ' + value(link.get('reverse_bps'), 'bps', 0))
    position = nx.spring_layout(graph, seed=12)
    primary, alternative = set(), set()
    for pair in definition.get('pairs', []):
        for path_name, nodes in pair['paths'].items():
            target = primary if selected.get(pair['pair_id'], pair['default_path']) == path_name else alternative
            target.update(frozenset((a, b)) for a, b in pairwise(nodes))
    figure = go.Figure()
    for a, b, data in graph.edges(data=True):
        active = frozenset((a, b)) in primary
        alternate = frozenset((a, b)) in alternative and not active
        figure.add_trace(go.Scatter(x=[position[a][0], position[b][0]], y=[position[a][1], position[b][1]], mode='lines',
            line={'color': TEAL if active else '#A7B8CA', 'width': 4 if active else 2, 'dash': 'dash' if alternate else 'solid'},
            hovertext=data['label'], hoverinfo='text', showlegend=False))
    for name, nodes, color, symbol in [('Switches', switches, NAVY, 'square'), ('Hosts', [h['host_id'] for h in hosts], TEAL, 'circle')]:
        figure.add_trace(go.Scatter(x=[position[n][0] for n in nodes], y=[position[n][1] for n in nodes], text=nodes,
            textposition='top center', mode='markers+text', name=name, marker={'size': 20, 'color': color, 'symbol': symbol},
            hoverinfo='text'))
    figure.update_layout(height=410, margin={'l': 20, 'r': 20, 't': 30, 'b': 10}, paper_bgcolor='white', plot_bgcolor='white',
        font={'color': NAVY}, xaxis={'visible': False}, yaxis={'visible': False}, legend={'orientation': 'h'})
    return figure


def network_controls(client, status, instance):
    with st.expander('Laboratory controls · intentional operations only'):
        st.caption('Controls affect only resources accepted by the privileged owner. Fault injection is separate experiment ground truth and is never sent to diagnosis.')
        with st.form('network_start_form'):
            new_id = st.text_input('New original instance ID', value='demo_' + st.session_state.setdefault('demo_suffix', uuid4().hex[:8]))
            mutation(client, 'network_start', 'Start owned network', '/v1/networks/start', {'instance_id': new_id}, disabled=not status['agent']['available'])
        if not instance:
            return
        with st.form('traffic_form'):
            profiles = st.multiselect('Configured traffic profiles', status['traffic_profiles'], default=status['traffic_profiles'][:2])
            duration = st.number_input('Traffic duration (seconds)', 1, 100, 30)
            mutation(client, 'traffic_start', 'Start traffic', '/v1/traffic/start',
                {'instance_id': instance, 'profile_ids': profiles, 'duration_s': int(duration), 'stream_receiver': True}, disabled=not profiles)
        with st.form('collector_form'):
            duration = st.number_input('Collector duration (seconds)', 25, 600, 120)
            stop = st.checkbox('Stop this collector instead of starting it')
            mutation(client, 'collector', 'Submit collector operation', '/v1/telemetry/stop' if stop else '/v1/telemetry/start',
                {'instance_id': instance} if stop else {'instance_id': instance, 'duration_s': int(duration)})
        with st.form('traffic_stop_form'):
            run_id = st.text_input('Traffic run ID to stop')
            mutation(client, 'traffic_stop', 'Stop traffic run', '/v1/traffic/stop', {'instance_id': instance, 'run_id': run_id}, disabled=not run_id)
        with st.form('fault_form'):
            st.markdown('**Controlled fault injection — laboratory ground truth**')
            operation = st.selectbox('Lab operation', ['Inject fault', 'Stop scenario', 'Restore scenario baseline'])
            kind = st.selectbox('Fault family', ['latency', 'loss', 'saturation', 'qos'])
            severity = st.selectbox('Severity', ['low', 'medium', 'high'])
            measurement = st.number_input('Fault measurement duration (seconds)', 4, 20, 20)
            confirmed = st.checkbox('I intend to run this bounded laboratory operation')
            path = {'Inject fault': 'start', 'Stop scenario': 'stop', 'Restore scenario baseline': 'reset'}[operation]
            payload = {'instance_id': instance}
            if operation == 'Inject fault':
                payload['scenario'] = {'kind': kind, 'severity': severity, 'measurement_s': int(measurement)}
            mutation(client, 'lab_fault', 'Submit laboratory operation', '/v1/laboratory/scenarios/' + path, payload, [confirmed])
        with st.form('cleanup_form'):
            operation = st.selectbox('Network lifecycle', ['Stop owned network', 'Clean up owned network'])
            confirm = st.checkbox('I confirm teardown of this owned lab and its traffic', key='confirm_teardown_' + instance)
            mutation(client, 'network_teardown', operation, '/v1/networks/' + ('cleanup' if operation.startswith('Clean') else 'stop'), {'instance_id': instance}, [confirm])


def telemetry(client, status):
    if status and any(b['purpose']=='main' and b['state']=='running' for b in status['dataset']['batches']):
        st.title('Network & Telemetry')
        st.info('The reserved dataset campaign owns this laboratory. Individual measurement views are withheld during collection to protect pending held-out episodes. Overview and Evidence retain structural progress.')
        return
    st.title('Network & Telemetry')
    st.caption('Actual topology and measured receiver/probe windows. Capacity is configured service, not observed throughput.')
    if not status:
        empty('Backend unavailable', 'Check the API connection before using laboratory controls.')
        return
    active_instance = select_network(status)
    instance = active_instance
    if not active_instance:
        sources = (read(client, '/v1/dashboard/telemetry-sources', Records) or {}).get('records', [])
        historical = choose(sources, 'historical_source', 'instance_id', 'Stored telemetry source · historical only')
        if historical:
            instance = historical['instance_id']
            st.info('Historical measurements only. This source is not a verified running network; it cannot be a mutation target. Live topology is unavailable.')
    if instance:
        network = read(client, '/v1/networks/' + instance) if active_instance else None
        if network and network.get('live_verified') and network.get('definition'):
            st.plotly_chart(topology_figure(network['definition'], network.get('selected_paths', {})), width='stretch')
            st.caption('Solid teal: selected routes · dashed gray: available alternate · hover a link for actual configured capacity.')
            table([{'Pair': p['pair_id'], 'Selected': network.get('selected_paths', {}).get(p['pair_id']),
                'Primary': ' → '.join(p['paths'].get('primary', [])), 'Alternate': ' → '.join(p['paths'].get('alternative', []))}
                for p in network['definition'].get('pairs', [])])
        data = read(client, f'/v1/dashboard/telemetry/{instance}?limit=60')
        windows = (data or {}).get('windows', [])
        if windows:
            latest = measurement_window(data['collector'], windows)
            if latest is not windows[0]:
                st.caption('The newest window is still accumulating. Showing the latest completed window from this collection; its quality gates still apply.')
            f = latest['features']
            badge('Measurement state', telemetry_freshness(data['collector'], latest))
            card_row([('Critical delivered', value(f.get('critical_goodput_bps'), 'bps', 0)), ('Mean RTT', value(f.get('rtt_mean_ms'), 'ms')),
                ('Receiver loss', value(None if f.get('udp_loss_fraction') is None else f['udp_loss_fraction'] * 100, '%')),
                ('Shared-link utilization', value(None if f.get('shared_utilization_fraction') is None else f['shared_utilization_fraction'] * 100, '%'))])
            st.caption(f"Source: native iperf receiver intervals, bounded ICMP probes and directional counters · UTC {latest['at_utc']} · Window {latest['window_id']}")
            if not latest['inference_ready']:
                st.warning('This window cannot support inference: ' + '; '.join(latest['data_quality'].get('reasons', [])))
            history = pd.DataFrame([{'UTC': w['at_utc'], 'Delivered (bps)': w['features'].get('critical_goodput_bps'),
                'RTT (ms)': w['features'].get('rtt_mean_ms'), 'Loss (%)': None if w['features'].get('udp_loss_fraction') is None else w['features']['udp_loss_fraction'] * 100,
                'Shared utilization (%)': None if w['features'].get('shared_utilization_fraction') is None else w['features']['shared_utilization_fraction'] * 100} for w in reversed(windows)])
            for name in history.columns.drop('UTC'):
                history[name] = pd.to_numeric(history[name], errors='coerce')
            st.caption('Stored history includes incomplete windows. Missing measurements appear as gaps, never zero-filled values.')
            for columns, names in [(st.columns(2), ['Delivered (bps)', 'RTT (ms)']), (st.columns(2), ['Loss (%)', 'Shared utilization (%)'])]:
                for column, name in zip(columns, names, strict=True):
                    with column:
                        st.markdown('**' + name + '**')
                        st.line_chart(history, x='UTC', y=name, color=TEAL, height=210)
            st.subheader('Measured flow delivery')
            table([{'Flow': k, **{n: v.get(n) for n in ('delivered_bps', 'duration_s', 'loss_fraction', 'jitter_ms')}} for k, v in latest.get('per_flow', {}).items()])
            st.subheader('Directional link utilization · stored counter measurements')
            table([{'Direction': direction, 'Measured utilization (%)':
                100 * row['weighted_utilization'] / row['duration_s'] if row.get('duration_s') and not row.get('invalid_intervals') else None,
                'Counter coverage (s)': row.get('duration_s'), 'Invalid intervals': len(row.get('invalid_intervals', []))}
                for direction, row in latest.get('directional', {}).items()])
            raw('Window quality and source detail', latest)
        else:
            empty('No stored measurements for this network', 'Start traffic and a collector. Missing values remain unavailable; configured capacity is never substituted.')
    network_controls(client, status, active_instance)


def incidents(client, status):
    st.title('Incidents & Diagnosis')
    st.caption('Observed symptoms, transparent rules and trained predictions are separate sources of evidence.')
    if not status:
        return empty('Backend unavailable', 'No diagnosis or model readiness can be inferred.')
    if not status['models']['active_model_id']:
        st.info('Trained diagnosis unavailable: no compatible model is activated. Observed symptoms and rule-based findings can still be recorded.')
    if not status['explanations']['ready_count']:
        st.info('SHAP unavailable: a compatible trained model and a real explanation for the selected observation are required.')
    selected = choose(records(client, 'incidents'), 'incident_select', 'incident_id', 'Recorded incident')
    if not selected:
        return empty('No incidents in the connected backend', 'Historical experiment outcomes are under Evidence. Empty history is not proof of healthy live service.')
    incident = read(client, '/v1/incidents/' + selected['incident_id'])
    if not incident:
        return
    card_row([('State', incident['state']), ('Severity', incident.get('severity', 'Unknown')), ('Service', incident.get('service_status', 'Unknown'))])
    st.caption('Observed UTC: ' + str(incident.get('observed_update_utc')))
    st.subheader('Observed symptoms and affected path')
    st.json(public_value(incident.get('path', {})))
    window_id = incident.get('last_window_id')
    if window_id:
        supporting = read(client, '/v1/dashboard/windows/' + window_id)
        if supporting:
            window = supporting['window']
            f = window['features']
            card_row([('Recorded mean RTT', value(f.get('rtt_mean_ms'), 'ms')),
                ('Recorded delivery', value(f.get('critical_goodput_bps'), 'bps', 0)),
                ('Recorded ping loss', value(None if f.get('ping_loss_fraction') is None else f['ping_loss_fraction'] * 100, '%'))])
            st.caption('Supporting observation: ' + window_id + ' · UTC ' + window['at_utc'] + ' · historical measurements')
            st.markdown('**Rule-based findings**')
            st.write((supporting.get('rule_findings') or {}).get('status', 'No saved rule result'))
            raw('Observed measurements and rule thresholds', supporting)
        findings = read(client, '/v1/diagnoses/' + window_id)
        for finding in (findings or {}).get('records', []):
            model_id = finding.get('model_id')
            st.subheader('Recorded trained-model prediction' if model_id else 'Observed / rule-based finding')
            st.write('Prediction:', finding.get('predicted_class', 'Unavailable'))
            if model_id:
                st.caption('Model ' + model_id + ' · calibrated confidence is shown only if explicitly supplied by the model result.')
                if finding.get('probability_status') == 'calibrated' and finding.get('confidence') is not None:
                    st.metric('Calibrated confidence', value(finding['confidence'] * 100, '%'))
                else:
                    st.caption('Calibrated confidence unavailable. Raw scores are not substituted.')
            raw('Finding details', finding)
        explanations = read(client, '/v1/explanations/window/' + window_id)
        diagnosed_models = {r['model_id'] for r in (findings or {}).get('records', []) if r.get('model_id')}
        ready = [e for e in (explanations or {}).get('records', []) if e.get('status') == 'ready'
            and e.get('window_id') == window_id and e.get('model_id') in diagnosed_models]
        if ready:
            st.subheader('Recorded SHAP explanation')
            for e in ready:
                st.caption('Model ' + e['model_id'] + ' · observation ' + window_id)
                result = e.get('result', e)
                contributions = result.get('contributions', [])
                if contributions:
                    frame = pd.DataFrame(contributions).sort_values('contribution', key=lambda s: s.abs(), ascending=False).head(10)
                    st.bar_chart(frame, x='transformed_feature', y='contribution', color=TEAL)
                raw('Actual explanation result', e)
        else:
            st.caption('No ready SHAP result exists for this incident observation.')
    raw('Incident measurements, rule findings and history', incident)


def twins(client, status):
    st.title('Digital Twin & Recommendations')
    st.caption('Twin measurements predict an outcome. Only fresh verification in the original laboratory can prove a repair.')
    if not status:
        return empty('Backend unavailable', 'Current twin fidelity and recommendation validity are unknown.')
    selected = choose(records(client, 'experiments'), 'experiment_select', 'operation_id', 'Candidate experiment')
    if not selected:
        empty('No candidate experiments in this backend', 'A qualified nominal reference and fresh source are required. Historical validation reports remain available under Evidence.')
    else:
        exp = read(client, '/v1/recovery/' + selected['operation_id'])
        if exp:
            card_row([('Experiment', exp['state']), ('Source snapshot', exp['snapshot_id']), ('Twin', exp['twin_id'])])
            snapshot = read(client, '/v1/twins/snapshots/' + exp['snapshot_id'])
            if snapshot:
                age = (datetime.now(UTC) - datetime.fromisoformat(snapshot.get('created_utc') or snapshot['at_utc'])).total_seconds()
                st.caption(f"Snapshot age: {age:,.0f} seconds · Expires UTC {snapshot['expires_utc']} · Original {snapshot['original_instance_id']}")
                raw('Observed hypotheses and snapshot provenance', snapshot)
            st.subheader('Measured candidate comparison · twin only')
            table(candidate_rows(exp))
            recommendation = exp.get('recommendation', {})
            st.write('Recommendation:', recommendation.get('status', 'Unavailable'))
            st.write('Selected candidate:', recommendation.get('selected_candidate_id') or 'None')
            table([{'Trial': t.get('trial_id'), 'Candidate': t.get('candidate_id'), 'Hypothesis': t.get('hypothesis_id'),
                'State': t.get('state'), 'Fidelity': t.get('fidelity', {}).get('status', t.get('fidelity', {}).get('passed')),
                'Failure': t.get('error')} for t in exp.get('trials', [])])
            raw('Fidelity residuals, no-change controls and recommendation evidence', exp)
            if exp.get('rejection_details'):
                st.subheader('Required versus observed: rejection details')
                table(exp['rejection_details'])
    table(records(client, 'twins'))


def workflow_form(client, status, instance, automated=False):
    with st.form('automation_form' if automated else 'workflow_form'):
        st.markdown('**Start a bounded monitor**' if automated else '**Observe and test a recommendation**')
        st.caption('Use an existing qualified nominal baseline and frozen fidelity policy. This control does not collect a dataset or train/calibrate a model.')
        baseline = st.text_area('Qualified baseline JSON', '{}', max_chars=16000, key='auto_baseline' if automated else 'baseline')
        policy = st.text_area('Frozen fidelity policy JSON', '{}', max_chars=16000, key='auto_policy' if automated else 'policy')
        repairs = st.selectbox('Distinct repair candidate budget', [2, 3], key='auto_repairs' if automated else 'repairs')
        confirm = st.checkbox('I intend to start this bounded workflow', key='confirm_monitor' if automated else 'confirm_workflow')
        try:
            payload = WorkflowRequest(instance_id=instance, workflow_id='w' + st.session_state.setdefault('workflow_suffix', uuid4().hex),
                request_key='k' + st.session_state.setdefault('workflow_key', uuid4().hex), baseline=json.loads(baseline), policy=json.loads(policy), max_repairs=repairs).model_dump()
        except (ValueError, TypeError):
            payload = {}
        valid = bool(payload.get('baseline', {}).get('window_ids') and payload.get('policy', {}).get('policy_hash'))
        mutation(client, 'automation_start' if automated else 'workflow_start', 'Start monitor' if automated else 'Start recommendation workflow',
            '/v1/lab/automation/start' if automated else '/v1/lab/workflow', payload, [confirm], disabled=not valid)
        if not valid:
            st.caption('Enter qualified baseline window_ids/definition_hash and the frozen policy_hash before submission.')


def recovery(client, status):
    st.title('Recovery & Audit')
    st.caption('Explicit scope. Measured verification. Recorded restoration.')
    if not status:
        return empty('Backend unavailable', 'Recovery controls require a reachable backend and its server-side gates.')
    control = read(client, '/v1/lab/control') or status['control']
    card_row([('Current backend mode', MODES[control['mode']]), ('Automatic actuation', 'Enabled' if control['auto_enabled'] else 'Disabled'),
        ('Observed-only exception', 'Enabled' if control['allow_observed_only'] else 'Disabled')])
    if control['allow_observed_only']:
        st.warning('OBSERVED-ONLY LAB OPERATION: this is a rule/measurement-driven path. It is not trained AI diagnosis or SHAP.')
    if st.button('Stop Automation', type='primary'):
        try:
            client.request('/v1/lab/automation/stop', 'POST', {})
            st.success('Stop acknowledged. Applied changes must finish verification or rollback.')
            st.rerun()
        except ApiError as exc:
            st.error(str(exc))
    with st.expander('Operating mode', expanded=True):
        modes = list(MODES)
        def reset_mode_confirmation():
            st.session_state.pop('confirm_auto', None)
            st.session_state.pop('confirm_observed', None)
        mode = st.selectbox('Requested mode', modes, index=modes.index(control['mode']), format_func=MODES.get,
            key='requested_mode', on_change=reset_mode_confirmation)
        allow = st.checkbox('Enable observed-only laboratory exception', value=control['allow_observed_only'],
            key='requested_exception', on_change=reset_mode_confirmation)
        with st.form('mode_form'):
            confirm_auto = st.checkbox('I explicitly confirm enabling automatic original-lab actuation', key='confirm_auto')
            confirm_observed = st.checkbox('I understand the exception uses observed rules/measurements, not trained AI', key='confirm_observed')
            mutation(client, 'mode_change', 'Apply mode selection', '/v1/lab/mode', {'mode': mode, 'allow_observed_only': allow},
                [mode != 'lab-auto-repair' or confirm_auto, not allow or confirm_observed])
    instance = select_network(status)
    if instance:
        with st.expander('Recommendation workflow / monitor'):
            workflow_form(client, status, instance)
            if control['auto_enabled']:
                workflow_form(client, status, instance, True)
    selected = choose(records(client, 'workflows'), 'workflow_select', 'workflow_id', 'Recorded recovery workflow')
    if selected:
        workflow = read(client, '/v1/lab/workflows/' + selected['workflow_id'])
        if workflow:
            st.subheader('Proposed original-lab change')
            st.write('Target:', workflow['instance_id'], '· State:', workflow['state'])
            if workflow.get('diagnosis', {}).get('status') == 'observed-only':
                st.warning('This workflow uses the explicit observed-only exception; it is not a trained-model diagnosis.')
            exp = read(client, '/v1/recovery/' + workflow['experiment_id']) if workflow.get('experiment_id') else None
            rec = (exp or {}).get('recommendation', {})
            st.json(public_value(rec.get('logical_diff', [])))
            raw('Eligibility evidence and rejection reasons', exp or workflow)
            if workflow.get('rejection_details'):
                table(workflow['rejection_details'])
            if workflow.get('diagnosis', {}).get('status') not in {None, 'supported', 'observed-only'}:
                st.warning('Trained diagnosis abstained: ' + '; '.join(workflow['diagnosis'].get('reasons', [])))
            st.info('Verification requires two fresh settled original windows, critical/protected service, unchanged workload/impairment, connectivity and readback. Rollback restores the recorded prior owned forwarding state. Route changes can temporarily lose packets.')
            applicability = read(client, '/v1/dashboard/applicable/' + workflow['workflow_id']) or {}
            eligible = bool(applicability.get('available'))
            st.caption(applicability.get('reason', 'Current application eligibility could not be verified.'))
            with st.form('apply_form'):
                confirm = st.checkbox('I confirm this proposed repair on the identified original laboratory', key='confirm_apply_' + workflow['workflow_id'])
                suffix = st.session_state.setdefault('apply_suffix', uuid4().hex)
                mutation(client, 'assisted_apply', 'Apply eligible repair', '/v1/lab/apply',
                    {'workflow_id': workflow['workflow_id'], 'action_id': 'a' + suffix, 'request_key': 'apply' + suffix}, [confirm], disabled=not eligible)
            if st.button('Cancel selected workflow'):
                try:
                    client.request('/v1/lab/cancel', 'POST', {'workflow_id': workflow['workflow_id']})
                    st.success('Cancellation requested. Applied configuration must be restored.')
                except ApiError as exc:
                    st.error(str(exc))
    actions = records(client, 'actions')
    st.subheader('Original action history')
    table(actions)
    selected_action = choose(actions, 'action_select', 'action_id', 'Action verification detail')
    if selected_action:
        action = read(client, '/v1/lab/actions/' + selected_action['action_id'])
        if action:
            table([{'Original verification window': p['window']['window_id'], 'Observed RTT (ms)': p.get('observed_rtt_mean_ms'),
                'Twin predicted RTT (ms)': str(p.get('predicted_rtt_mean_ms')), 'Passed': p['evaluation']['eligible']} for p in action.get('post_windows', [])])
            transient = action.get('transient_disruption')
            if transient:
                st.markdown('**Application disruption · separate from settled verification**')
                table([{'Flow': flow, **metrics} for flow, metrics in (transient.get('metrics') or {}).items()])
                st.caption(transient.get('resolution', transient.get('reason', '')))
            else:
                st.caption('Application-overlap loss was not recorded on this action. Missing does not mean zero.')
            raw('Action, rollback and error details', action)
    if instance:
        undo = read(client, '/v1/dashboard/reversible/' + instance)
        st.caption((undo or {}).get('reason', 'Undo applicability unavailable.'))
        with st.form('undo_form'):
            confirm = st.checkbox('I confirm undo of the backend-identified reversible action', key='confirm_undo_' + instance)
            mutation(client, 'undo', 'Undo Last Lab Action', '/v1/lab/undo',
                {'instance_id': instance, 'action_id': (undo or {}).get('action_id'), 'request_key': 'undo' + st.session_state.setdefault('undo_suffix', uuid4().hex)},
                [confirm], disabled=not (undo or {}).get('available'))
    with st.expander('Recent audit events'):
        table(records(client, 'audit'))


def evidence(client, status):
    st.title('Evidence & Project Information')
    st.caption('Implemented infrastructure and experimentally demonstrated capabilities are reported separately.')
    if status:
        st.subheader('Connected backend dataset')
        counts = status['dataset']['counts_by_split']
        table([{'Split': k, 'Accepted windows': counts.get(k, 0)} for k in ('train', 'validation', 'test', 'pilot')])
        table(status['dataset']['batches'])
        st.caption('Split counts are structural metadata. Sealed test measurements are not opened by this dashboard.')
    items = (read(client, '/v1/dashboard/evidence', Records) or {}).get('records', [])
    st.subheader('Approved evidence library')
    st.caption('Sanitized evidence summaries and timestamped campaign checkpoints. These are separate from live telemetry. Software checks are labeled separately from laboratory measurements.')
    for item in items:
        with st.container(border=True):
            st.markdown('#### ' + item['title'])
            st.caption(item['kind'])
            if item['available']:
                data = read(client, '/v1/dashboard/evidence/' + item['artifact_id'])
                if data:
                    r = data['evidence']
                    st.write('Recorded status:', r.get('status', 'See report'))
                    if item['artifact_id'] == 'completion3':
                        st.caption('Separate prospective cohort; the connected backend above retains its own dataset/model identity.')
                        table([{'Accepted windows':r.get('accepted_windows'),'Target windows':r.get('expected_windows'),
                            'Completed episodes':r.get('completed_episodes'),'Target episodes':r.get('expected_episodes'),
                            'Dataset ready':r.get('dataset_ready'),'Partitions':str(r.get('partitions'))}])
                        metric=r.get('held_out_metrics') or {}
                        if metric:
                            table([{'Held-out windows':metric.get('windows'),'Episodes':metric.get('episodes'),
                                'Families':metric.get('families'),'Macro F1':metric.get('window_classification',{}).get('macro_f1'),
                                'Supported coverage':metric.get('abstention',{}).get('coverage_fraction')}])
                        else:st.info('New model/held-out metrics remain pending until the audited corpus is complete.')
                        if r.get('blockers'):st.warning('; '.join(r['blockers']))
                    if item['artifact_id'] == 'evaluation':
                        metric = r.get('held_out_metrics') or {}
                        if metric:
                            st.caption('Held-out episode results · frozen model · measured main dataset')
                            table([{'Split':metric.get('split'),'Windows':metric.get('windows'),
                                'Episodes':metric.get('episodes'),'Model':metric.get('model_id'),
                                'Macro F1':metric.get('window_classification',{}).get('macro_f1'),
                                'Accuracy':metric.get('window_classification',{}).get('accuracy'),
                                'Supported coverage':metric.get('abstention',{}).get('coverage_fraction')}])
                        table([{k:v for k,v in row.items() if not isinstance(v,(dict,list))}
                            for row in r.get('baseline_results',[])])
                        table([{k:v for k,v in row.items() if not isinstance(v,(dict,list))}
                            for row in r.get('scale_results',[])])
                        if r.get('blockers'):
                            st.warning('; '.join(r['blockers']))
                    if item['artifact_id'] == 'integration':
                        st.caption('Recorded integration rehearsal checkpoints; completed observations are historical, not live telemetry.')
                        table([{'Run': row.get('tag'), 'Source': row.get('source_id'), 'Started UTC': row.get('started_utc'),
                            'Mode': row.get('mode'), 'Outcome': row.get('status'), 'Pre RTT (ms)': row.get('before_rtt_ms'),
                            'Verified RTT (ms)': row.get('after_rtt_ms'), 'Critical (bps)': row.get('after_critical_bps'),
                            'Bulk (bps)': row.get('after_bulk_bps'), 'Verified windows': row.get('post_window_count'),
                            'Owned cleanup': row.get('owned_cleanup')} for row in r.get('rehearsal', [])])
                        st.caption('Automated software fixtures and lifecycle checks are separate from packet evidence.')
                        table([{'Passed tests': row.get('passed'), 'Duration (s)': row.get('elapsed_s'),
                            'Scope': row.get('scope')} for row in r.get('checks', {}).get('software', {}).get('tests', [])])
                        if r.get('limitations'):
                            st.write('Declared limits:', r['limitations'])
                    if item['artifact_id'] == 'recovery':
                        rows = []
                        for name, case in r.get('summary', {}).items():
                            rows.append({'Historical native case': name, 'Outcome': case['state'], 'Pre RTT (ms)': case.get('pre_rtt_mean_ms'),
                                'Settled RTT (ms)': str(case.get('post_rtt_mean_ms', case.get('restored_rtt_mean_ms', 'Unavailable')))})
                        table(rows)
                        with st.expander('Historical application disruption'):
                            for name, case in r.get('summary', {}).items():
                                st.write(name)
                                table([{'Flow': flow, **metrics} for flow, metrics in (case.get('transient_disruption', {}).get('metrics') or {}).items()])
                    if r.get('software_verification'):
                        raw('Software-test verification · not packet evidence', r['software_verification'])
                    st.download_button('Download approved summary', json.dumps(data, indent=2), file_name='explainnet-' + item['artifact_id'] + '.json',
                        mime='application/json', key='download_' + item['artifact_id'])
                    raw('Report summary', r)
            else:
                st.caption('Artifact unavailable. No replacement values are generated.')
    st.subheader('Current limitations')
    st.write('Production readiness depends on the complete measured dataset, compatible trained model, actual model/window SHAP, fresh twin fidelity and independently qualified repair scope. Historical UDP latency success does not qualify other faults. An observed-only exception must remain explicit.')
    st.subheader('Architecture')
    st.graphviz_chart('digraph { rankdir=LR; node [shape=box style="rounded,filled" fillcolor="#EFF7F8" color="#142D4E"]; "Streamlit UI" -> "Unprivileged API"; "Unprivileged API" -> "SQLite evidence"; "Unprivileged API" -> "Privileged agent" [label="typed local socket"]; "Privileged agent" -> "Owned original lab"; "Privileged agent" -> "Isolated twin"; "Ground truth" -> "Experiment evaluation"; }')
    with st.expander('Demonstration glossary'):
        table([{'Term': t, 'Meaning': meaning} for t, meaning in [('RTT', 'Round-trip time, in milliseconds.'), ('Goodput', 'Receiver-delivered useful data, in bits per second.'),
            ('Loss', 'Missing packets as a fraction; the UI may display percent.'), ('Fidelity', 'A measured twin/control agreement gate, not a claim of identical systems.'),
            ('SHAP', 'Contributions for a specific trained model and observation; not a physical-cause proof.'), ('Observed-only', 'Explicit laboratory exception driven by rules and measurements.'),
            ('Rollback', 'Restore the recorded previous owned configuration and verify it.'), ('Stale', 'Historical or materially invalid evidence that cannot authorize a current action.')]])
    st.subheader('Project team')
    st.write('Visweswar Sarma — [registration redacted]')
    st.write('Shafin Khan — [registration redacted]')
    st.write('Anushka Jain — [registration redacted]')


RENDERERS = [overview, telemetry, incidents, twins, recovery, evidence]


def render(page, client):
    status = read(client, '/v1/dashboard/status', DashboardStatus)
    slot = st.session_state.get('_shell_status_slot')
    if slot is not None:
        from explainnet.dashboard.shell import status_panel
        with slot.container():
            if not status_panel(client, status, read):
                return
    if status and status['control'].get('allow_observed_only') and page != 4:
        st.warning('Observed-only laboratory exception is enabled. This path uses rules and measurements, not trained AI diagnosis.')
    RENDERERS[page](client, status)
    activity(client)
    st.caption('ExplainNet Twin · Local laboratory only · All observation timestamps are UTC · Swagger remains developer documentation.')


def render_selected(page):
    client = ApiClient()
    interval = '10s' if st.session_state.get('refresh_active_view', False) else None
    st.fragment(run_every=interval)(lambda: render(page, client))()
