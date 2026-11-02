"""Four context-aware pages over the existing typed API and actuation gates."""
import json
from datetime import UTC, datetime
from uuid import uuid4

import plotly.graph_objects as go
import streamlit as st

from explainnet.dashboard.client import ApiClient
from explainnet.dashboard.presentation import candidate_rows, measurement_window, telemetry_freshness, value
from explainnet.dashboard.theme import plot_theme
from explainnet.dashboard.views import (
    activity,
    card_row,
    empty,
    mutation,
    raw,
    read,
    records,
    table,
    topology_figure,
)

PAGES=['Live Network','Diagnosis','Twin & Recovery','Results']


def scoped(rows,instance,field='instance_id'):
    return [r for r in rows if not instance or r.get(field)==instance]


def history(rows,key,id_field,label):
    if not rows:return None
    ordered=sorted(rows,key=lambda r:r.get('observed_update_utc') or r.get('created_utc') or '',reverse=True)
    ids=[r[id_field] for r in ordered]
    if st.session_state.get(key) not in ids:st.session_state.pop(key,None)
    labels={r[id_field]:f"{r.get('observed_update_utc') or r.get('created_utc') or 'Recorded time unavailable'} · {r.get('state','unknown')} · {r.get('instance_id',r.get('original_instance_id','source'))}" for r in ordered}
    chosen=st.selectbox(label,ids,format_func=labels.get,key=key)
    return next(r for r in ordered if r[id_field]==chosen)


def context_network(status):
    if not status:return None
    selected=st.session_state.get('selected_original')
    live=[r['instance_id'] for r in status['agent']['instances'] if r.get('role')=='original' and r.get('state')=='running' and r.get('live_verified')]
    return selected if selected in live else live[0] if live else None


def refusal_rows(value,path=''):
    """Retain nested metric failures instead of flattening to a generic label."""
    rows=[]
    if isinstance(value,dict):
        for key,item in value.items():
            location=(path+'.'+key).strip('.')
            if key in {'error','reason','reasons','stale_reasons','missing_required_metrics','contamination'} and item:
                rows.append({'Evidence location':location,'Reason':'; '.join(map(str,item)) if isinstance(item,list) else str(item)})
            elif key in {'metrics','metric_checks','checks','residuals'} or isinstance(item,(dict,list)) and key not in {'features','per_flow','samples','contributions','native'}:
                rows.extend(refusal_rows(item,location))
        if (value.get('passed') is False or value.get('status')=='fail') and not value.get('metrics'):
            scalar={k:v for k,v in value.items() if not isinstance(v,(dict,list))}
            if value.get('metric'):
                reason=f"{value['metric']}: original {value.get('original')}, twin {value.get('twin')}, absolute difference {value.get('absolute_error',value.get('error'))}, allowed tolerance {value.get('tolerance')}; {value.get('status')}"
            else:reason='; '.join(str(k)+': '+str(v) for k,v in scalar.items() if 'hash' not in k)
            if reason:rows.append({'Evidence location':path,'Reason':reason})
    elif isinstance(value,list):
        for i,item in enumerate(value):rows.extend(refusal_rows(item,f'{path}[{i}]'))
    return rows


def operation(client,slot,label,path,payload,disabled=False,destructive=False):
    with st.form(slot+'_form'):
        confirm=st.checkbox('I confirm this operation on the selected owned laboratory',key=slot+'_confirm') if destructive else True
        return mutation(client,slot,label,path,payload,[confirm],disabled=disabled)


def running_traffic(client,network):
    result=[]
    for run_id in (network or {}).get('runs',[])[-8:]:
        run=read(client,f"/v1/traffic/{network['instance_id']}/{run_id}")
        if run and run.get('state')=='running':result.append(run)
    return result


def guide(client,status,instance,host):
    with st.expander('Guided teacher demonstration',expanded=not instance):
        st.caption('Every operation below requires a click. Refresh, profile switching and navigation only read state. Default mode is Recommend; automatic repair stays off until explicitly enabled.')
        if host.get('active'):
            st.warning(host['reason']);st.info('Review saved evidence in Diagnosis, Twin & Recovery and Results. Resume live demonstration after the campaign finishes; do not launch concurrent rehearsals.');return
        ctl=status['control'];busy=bool(ctl.get('active_workflow_id') or ctl.get('monitor_active') or ctl.get('unsettled_action_ids') or ctl.get('cleanup_pending_workflow_ids'))
        plan=st.selectbox('Planned laboratory fault',['latency','loss','saturation','qos'],key='demo_planned_fault')
        st.markdown('**1 · Prepare a healthy network** — allow about 10–20 seconds for construction, then start the bounded workload and collector.')
        if not instance:
            suffix=st.session_state.setdefault('guided_instance',uuid4().hex[:10])
            operation(client,'guided_create','Prepare owned network','/v1/networks/start',{'instance_id':'demo_'+suffix},disabled=not status['agent']['available'])
            return
        network=read(client,'/v1/networks/'+instance) or {};runs=running_traffic(client,network)
        journal=(read(client,'/v1/laboratory/scenarios/'+instance) or {}).get('laboratory_journal') or {}
        impaired=journal.get('state') not in {None,'stopped'} and journal.get('configuration',{}).get('kind')!='healthy'
        telemetry=read(client,'/v1/dashboard/telemetry/'+instance+'?limit=10') or {}
        collector=telemetry.get('collector',{})
        if impaired:st.warning('An impairment is active. Healthy renewal is blocked until explicit restoration. Keep it active during repair verification.')
        nominal_profiles=[{'schema_version':1,'config_version':'workflow_observation_v1','profile_id':p,
            'source_host':a,'target_host':b,'protocol':'udp','offered_bps':rate,'packet_size':1200,
            'duration_s':900,'warmup_s':3,'stream_receiver':True}
            for p,a,b,rate in [('critical','h1','h3',2_000_000 if plan=='qos' else 8_000_000),('bulk','h2','h4',5_000_000)]]
        operation(client,'guided_traffic','Start / renew healthy traffic (15 min)','/v1/traffic/workload/start',
            {'instance_id':instance,'profiles':nominal_profiles},disabled=busy or impaired or bool(runs))
        operation(client,'guided_collector','Start / renew monitoring (15 min)','/v1/telemetry/start',
            {'instance_id':instance,'duration_s':900},disabled=busy or bool(collector.get('live')) or not runs)
        st.markdown('**2 · Observe fresh healthy measurements and register a nominal reference** — wait about 30 seconds, then capture two actual 15-second windows.')
        operation(client,'guided_reference','Capture healthy reference','/v1/demo/reference',{'instance_id':instance},disabled=busy or impaired or not runs)
        reference=(read(client,'/v1/demo/reference/'+instance) or {}).get('reference')
        st.caption('Nominal reference: '+('registered at '+reference['created_utc'] if reference else 'not registered'))
        st.markdown('**3 · Introduce the selected fault** — stop nominal monitoring and traffic first, then inject the fault and restart monitoring. Each submission is separately acknowledged.')
        operation(client,'guided_stop_monitor','Stop monitoring','/v1/telemetry/stop',{'instance_id':instance},disabled=busy or not collector.get('live'))
        for index,run in enumerate(runs):
            operation(client,'guided_stop_traffic_'+str(index),'Stop selected workload '+str(index+1),'/v1/traffic/stop',
                {'instance_id':instance,'run_id':run['run_id']},disabled=busy)
        scenario={'schema_version':1,'config_version':'recovery_observation_v1','kind':plan,'severity':'high','warmup_s':3,
            'measurement_s':900,'traffic_profile':'shared' if plan=='saturation' else 'qos_competing' if plan=='qos' else 'moderate',
            'critical_bps':2_000_000 if plan=='qos' else 8_000_000,'bulk_protocol':'udp','packet_size':1200,'seed':20261016,
            'bidirectional':False,'variation_ms':0,'high_utilization':False}
        operation(client,'guided_fault','Introduce '+plan+' fault (15 min)','/v1/laboratory/scenarios/start',
            {'instance_id':instance,'scenario':scenario},disabled=busy or not reference or bool(runs) or bool(collector.get('live')) or impaired,destructive=True)
        st.markdown('**4 · Diagnosis** — restart monitoring above, wait for fresh windows, then open Diagnosis. A trained supported prediction and matching SHAP must actually exist.')
        st.markdown('**5–6 · Twin validation and recommendation** — open Twin & Recovery. Run the bounded comparison using the registered nominal reference (typically several minutes; no <10-second claim).')
        st.markdown('**7–8 · Assisted repair and verification** — select Assisted mode explicitly, review eligibility and proposed changes, confirm Apply, then inspect two fresh original verification windows or rollback.')
        st.markdown('**9 · Restore only when requested** — Undo an applicable kept action in Twin & Recovery, stop monitoring/traffic, then restore the scenario and optionally clean this owned lab.')
        operation(client,'guided_restore','Restore scenario baseline','/v1/laboratory/scenarios/reset',{'instance_id':instance},disabled=busy,destructive=True)
        operation(client,'guided_cleanup','Clean selected owned laboratory','/v1/networks/cleanup',{'instance_id':instance},disabled=busy or bool(runs) or bool(collector.get('live')),destructive=True)


def live(client,status,host):
    st.title('Live Network');st.caption('Owned topology and actual packet measurements. Configured capacity and measured utilization are separate.')
    if not status:return empty('Backend unavailable','Persistent controls remain available. No live values or readiness are inferred.')
    instance=context_network(status)
    guide(client,status,instance,host)
    historical=False
    if not instance:
        rows=(read(client,'/v1/dashboard/telemetry-sources') or {}).get('records',[])
        chosen=history(rows,'live_history','instance_id','Stored network history')
        instance=chosen['instance_id'] if chosen else None;historical=True
        st.info('No verified active original. Stored measurements below are historical; they cannot authorize repair.')
    if not instance:return
    network=read(client,'/v1/networks/'+instance) if not historical else None
    if network and network.get('definition'):
        fig=topology_figure(network['definition'],network.get('selected_paths',{}));plot_theme(fig)
        for trace in fig.data:
            if getattr(trace,'name',None)=='Switches':trace.marker.color='#8DABDF'
        st.plotly_chart(fig,width='stretch')
        table([{'Traffic':p['pair_id'],'Selected route':network.get('selected_paths',{}).get(p['pair_id']),
            'Primary':' → '.join(p['paths'].get('primary',[])),'Alternative':' → '.join(p['paths'].get('alternative',[]))} for p in network['definition']['pairs']])
        with st.expander('Configured directional capacity and topology'):
            table(network['definition']['links']);raw('Logical definition',network['definition'])
    data=read(client,'/v1/dashboard/telemetry/'+instance+'?limit=60') or {};windows=data.get('windows',[])
    if not windows:return empty('No measurements','Start a workload and monitoring intentionally. Missing metrics remain unavailable.')
    latest=measurement_window(data.get('collector',{}),windows);f=latest['features']
    st.info(telemetry_freshness(data.get('collector',{}),latest)+' · observation '+latest['at_utc'])
    card_row([('Critical delivery',value(f.get('critical_goodput_bps'),'bps',0)),('RTT mean',value(f.get('rtt_mean_ms'),'ms')),
        ('Receiver loss',value(f.get('udp_loss_fraction'),'fraction')),('Receiver jitter',value(f.get('udp_jitter_ms'),'ms'))])
    rows=[{'UTC':w['at_utc'],**{k:w['features'].get(k) for k in ['rtt_mean_ms','critical_goodput_bps','udp_loss_fraction','udp_jitter_ms','shared_utilization_fraction']}} for w in reversed(windows)]
    for key,title,unit in [('rtt_mean_ms','Round-trip time','ms'),('critical_goodput_bps','Critical delivered rate','bits/s'),('udp_loss_fraction','Receiver packet loss','fraction'),('udp_jitter_ms','Receiver jitter','ms')]:
        fig=go.Figure(go.Scatter(x=[r['UTC'] for r in rows],y=[r[key] for r in rows],mode='lines+markers',connectgaps=False,name=title,line={'color':'#37B5AD'}))
        fig.update_layout(title=title,height=230,xaxis_title='Observation UTC',yaxis_title=unit,margin={'t':45,'b':35})
        st.plotly_chart(plot_theme(fig),width='stretch')
    st.subheader('Critical and protected traffic');table([{'Flow':k,**v} for k,v in latest.get('per_flow',{}).items()])
    with st.expander('Measured utilization and quality'):
        table([{'Direction':k,'Measured utilization fraction':v.get('weighted_utilization',0)/v['duration_s'] if v.get('duration_s') and not v.get('invalid_intervals') else None,'Coverage (s)':v.get('duration_s')} for k,v in latest.get('directional',{}).items()])
        raw('Quality and provenance',latest)


def diagnosis(client,status,host):
    del host
    st.title('Diagnosis');st.caption('Transparent rule findings and trained IF/RF results remain distinct. SHAP must match the selected model and observation.')
    if not status:return empty('Backend unavailable','No diagnosis readiness is inferred.')
    instance=context_network(status)
    if instance and st.checkbox('Browse recorded incidents from other networks',value=False,key='diagnosis_other_networks'):
        instance=None
    rows=scoped(records(client,'incidents'),instance)
    if instance:
        data=read(client,'/v1/dashboard/telemetry/'+instance+'?limit=1') or {}
        session_start=((data.get('collector') or {}).get('session') or {}).get('started_utc')
        earlier=st.checkbox('Include earlier sessions for this network',value=False,key='diagnosis_earlier')
        if session_start and not earlier:
            rows=[r for r in rows if (r.get('observed_update_utc') or '')>=session_start]
        if earlier:st.info('Earlier-session history is enabled. These incidents may be stale and do not establish current eligibility.')
    if not instance:st.info('No live original is selected. Showing explicitly recorded incident history.')
    chosen=history(rows,'diagnosis_history','incident_id','Incident history for selected network')
    if not chosen:return empty('No relevant incident','Healthy operation need not create an incident. Observe current measurements on Live Network.')
    incident=read(client,'/v1/incidents/'+chosen['incident_id']) or {};wid=incident.get('last_window_id')
    if not wid:return
    observed=read(client,'/v1/dashboard/windows/'+wid) or {};w=observed.get('window',{})
    if w and w.get('instance_id')!=incident.get('instance_id'):return st.error('Incident/window network lineage mismatch; diagnosis withheld.')
    card_row([('Incident state',incident.get('state')),('Affected service',incident.get('service_status')),('Observation UTC',w.get('at_utc','Unavailable'))])
    path=incident.get('path',{});nodes=path.get('switches',path.get('path')) or []
    st.write('Affected traffic/path:',path.get('flow'),path.get('path_name'),' → '.join(nodes) if isinstance(nodes,list) else nodes)
    st.subheader('Observed symptoms and rules');f=w.get('features',{})
    table([{'RTT p95 (ms)':f.get('rtt_p95_ms'),'Delivery (bps)':f.get('critical_goodput_bps'),'Probe loss fraction':f.get('ping_loss_fraction')}])
    rule=observed.get('rule_findings') or {};st.write('Rule status:',rule.get('status','Unavailable'))
    table([{k:x.get(k) for k in ['rule','actual','threshold','unit','affected']} if isinstance(x,dict) else {'Finding':str(x)} for x in rule.get('violations',[])])
    findings=(read(client,'/v1/diagnoses/'+wid) or {}).get('records',[])
    active=status['models'].get('active_model_id')
    candidates=[d for d in findings if d.get('model_id')==active] or [d for d in findings if d.get('model_id')]
    if not candidates:return empty('Trained result unavailable for this observation','Rules are not a substitute for a trained diagnosis. No current matching explanation is implied by saved counts.')
    candidates=[d for d in candidates if d.get('mode')=='live'] or candidates
    d=candidates[-1];st.subheader('Actual trained pipeline')
    card_row([('Operational support',d.get('status')),('RF prediction',d.get('predicted_class')),('IF anomalous',d.get('anomalous')),('IF score',d.get('anomaly_score'))])
    st.write('Support reasons:',d.get('reasons') or ['No refusal reason supplied'])
    probabilities=d.get('calibrated_probabilities')
    if probabilities:table([{'Class':k,'Calibrated probability':v} for k,v in probabilities.items()])
    else:st.caption('Calibrated probabilities unavailable. Raw RF scores are available only in technical details.')
    explanations=(read(client,'/v1/explanations/window/'+wid) or {}).get('records',[])
    matching=[x for x in explanations if x.get('window_id')==wid and x.get('model_id')==d.get('model_id') and x.get('mode')==d.get('mode')]
    ready=[x for x in matching if x.get('status')=='ready']
    if ready:
        x=ready[-1];result=x.get('result') or x;st.subheader('Matching per-event SHAP')
        st.caption('Raw RF probability contributions, separate from calibrated confidence; not physical causality.')
        contributions=result.get('contributions',[])
        top=sorted(contributions,key=lambda c:abs(c.get('contribution',0)),reverse=True)[:10]
        if top:
            fig=go.Figure(go.Bar(x=[c['contribution'] for c in top],y=[c.get('transformed_feature',c.get('original_feature')) for c in top],orientation='h',marker_color=['#37B5AD' if c['contribution']>=0 else '#E88E8E' for c in top]))
            fig.update_layout(height=380,xaxis_title='Change in raw RF class probability',yaxis={'autorange':'reversed'},margin={'l':20,'r':20,'t':15,'b':35})
            st.plotly_chart(plot_theme(fig),width='stretch');table([{k:c.get(k) for k in ['original_feature','feature_value','contribution','direction']} for c in top])
        st.write(x.get('plain_language') or result.get('plain_language') or result.get('interpretation',''))
        raw('SHAP lineage and additivity',x)
    else:st.warning('No ready SHAP for this exact model/window. '+('; '.join(str(x.get('error') or x.get('status')) for x in matching) or 'No matching request exists.'))
    raw('Observation, trained result and incident history',{'window':w,'diagnosis':d,'incident':incident})


def experiment_view(client,exp):
    st.subheader('Twin measurements and candidate comparison');st.write('Experiment state:',exp.get('state'),'·',exp.get('progress',''))
    snapshot=read(client,'/v1/twins/snapshots/'+exp['snapshot_id']) if exp.get('snapshot_id') else None
    if snapshot:
        stamp=snapshot.get('created_utc') or snapshot.get('at_utc');age=(datetime.now(UTC)-datetime.fromisoformat(stamp)).total_seconds() if stamp else None
        st.caption(f"Snapshot age {value(age,'s',0)} · expires UTC {snapshot.get('expires_utc')} · source version {snapshot.get('source_fingerprint','Unavailable')[:16]}")
        st.write('Reconstruction uncertainty:',snapshot.get('uncertainty') or snapshot.get('hypotheses') or 'See retained reconstruction details')
        raw('Snapshot versions and reconstruction',snapshot)
    table(candidate_rows(exp))
    comparisons=[]
    for trial in exp.get('trials',[]):
        left=(trial.get('original_window') or {}).get('features',{});right=(trial.get('window') or {}).get('features',{})
        comparisons.append({'Treatment':trial.get('family'),'Repeat':trial.get('repetition'),'Hypothesis':trial.get('hypothesis_id'),
            'State':trial.get('state'),'Original RTT (ms)':left.get('rtt_mean_ms'),'Twin RTT (ms)':right.get('rtt_mean_ms'),
            'Original delivery (bps)':left.get('critical_goodput_bps'),'Twin delivery (bps)':right.get('critical_goodput_bps'),
            'Original loss fraction':left.get('udp_loss_fraction'),'Twin loss fraction':right.get('udp_loss_fraction')})
        fidelity=trial.get('fidelity')
        if fidelity:
            st.markdown('**No-change fidelity · '+str(trial.get('repetition'))+' · '+str(fidelity.get('status'))+'**')
            metrics=fidelity.get('metrics',{})
            table([{'Metric':k,**v} for k,v in metrics.items()] if isinstance(metrics,dict) else metrics)
    table(comparisons)
    for trial in exp.get('trials',[]):
        with st.expander('Protected flows and trial detail · '+str(trial.get('family'))+' · '+str(trial.get('repetition'))):
            table([{'Flow':k,**v} for k,v in (trial.get('window') or {}).get('per_flow',{}).items()]);raw('Trial record',trial)
    rec=exp.get('recommendation') or {};st.write('Recommendation:',rec.get('status','Unavailable'))
    table(rec.get('rows',[]));st.write('Proposed logical change:',rec.get('logical_diff') or 'None')
    reasons=refusal_rows(exp)
    if reasons:st.subheader('Exact refusal and trial reasons');table(reasons)
    raw('Full candidate and fidelity evidence',exp)


def twin_recovery(client,status,host):
    st.title('Twin & Recovery');st.caption('Observation → snapshot → reconstruction → fidelity → trials → recommendation → optional application → verification or rollback')
    if not status:return empty('Backend unavailable','Actuation remains unavailable. Refresh does not submit work.')
    instance=context_network(status)
    history_instance=None if st.checkbox('Browse recorded recovery history from other networks',value=False,key='recovery_other_networks') else instance
    if host.get('active'):st.warning(host['reason'])
    control=status['control'];blocked=host.get('active',False)
    with st.expander('Operating mode and explicit laboratory consent'):
        mode=st.selectbox('Requested mode',['recommend','assisted-repair','lab-auto-repair','observe'],key='v4_mode')
        identity=(read(client,'/v1/config') or {}).get('identity',{})
        with st.form('v4_mode_form'):
            auto=st.checkbox('I explicitly enable automatic actuation in this owned laboratory only')
            observed=st.checkbox('Enable the explicit observed-only laboratory exception') if identity.get('profile')=='observed-only' else False
            acknowledge=st.checkbox('I understand this uses rules and measurements and cannot qualify trained recovery') if identity.get('profile')=='observed-only' else False
            mutation(client,'v4_mode','Apply operating mode','/v1/lab/mode',{'mode':mode,'allow_observed_only':observed},
                [mode!='lab-auto-repair' or auto,not observed or acknowledge],disabled=blocked)
        st.caption('Trained profile never silently enables an observed-only exception. Automatic mode requires explicit consent and qualified server evidence.')
    if st.button('Stop Automation',key='v4_stop'):
        client.request('/v1/lab/automation/stop','POST',{});st.success('Stop acknowledged; in-flight verification/rollback must settle.')
    if instance:
        reference=(read(client,'/v1/demo/reference/'+instance) or {}).get('reference')
        if reference:
            workflow_id='demo_w'+st.session_state.setdefault('v4_workflow_suffix',uuid4().hex)
            operation(client,'v4_workflow','Run twin validation and compare two repairs','/v1/lab/workflow',
                {'instance_id':instance,'workflow_id':workflow_id,'request_key':workflow_id,'baseline':reference['baseline'],
                    'policy':reference['policy'],'max_repairs':2,'max_hypotheses':2,'timeout_s':900},disabled=blocked or bool(control.get('active_workflow_id')))
            if control.get('auto_enabled'):
                operation(client,'v4_monitor','Start explicitly enabled bounded monitor','/v1/lab/automation/start',
                    {'instance_id':instance,'workflow_id':workflow_id,'request_key':workflow_id,'baseline':reference['baseline'],
                        'policy':reference['policy'],'max_repairs':2,'max_hypotheses':2,'timeout_s':900},disabled=blocked,destructive=True)
        else:st.info('Capture a healthy nominal reference on Live Network before starting comparisons. No pasted IDs or policy JSON are needed.')
    workflows=scoped(records(client,'workflows'),history_instance);selected=history(workflows,'v4_workflow_history','workflow_id','Workflow history')
    workflow=read(client,'/v1/lab/workflows/'+selected['workflow_id']) if selected else None
    if workflow:
        st.write('Workflow:',workflow['state']);table(refusal_rows(workflow))
        exp=read(client,'/v1/recovery/'+workflow['experiment_id']) if workflow.get('experiment_id') else None
        if exp:experiment_view(client,exp)
        applicability=read(client,'/v1/dashboard/applicable/'+workflow['workflow_id']) or {}
        st.caption(applicability.get('reason','Eligibility unavailable'))
        action_id='demo_a'+st.session_state.setdefault('v4_action_suffix',uuid4().hex)
        operation(client,'v4_apply','Apply eligible assisted repair','/v1/lab/apply',{'workflow_id':workflow['workflow_id'],
            'action_id':action_id,'request_key':action_id},disabled=blocked or workflow.get('instance_id')!=instance or control['mode']!='assisted-repair' or not applicability.get('available'),destructive=True)
        if st.button('Cancel selected workflow',key='v4_cancel'):
            client.request('/v1/lab/cancel','POST',{'workflow_id':workflow['workflow_id']});st.info('Cancellation requested. Applied changes must finish rollback before cleanup.')
    else:
        experiments=records(client,'experiments')
        if instance:
            relevant={s['snapshot_id'] for s in scoped(records(client,'snapshots'),instance,'original_instance_id')}
            experiments=[e for e in experiments if e.get('snapshot_id') in relevant]
        selected_exp=history(experiments,'v4_experiment_history','operation_id','Recorded candidate experiments')
        if selected_exp:
            exp=read(client,'/v1/recovery/'+selected_exp['operation_id'])
            if exp:experiment_view(client,exp)
        else:st.info('No candidate experiment exists for this context. Historical qualification is in Results; it does not authorize current application.')
    st.subheader('Original verification and restoration')
    selected_action=history(scoped(records(client,'actions'),history_instance),'v4_action_history','action_id','Original action history')
    if selected_action:
        action=read(client,'/v1/lab/actions/'+selected_action['action_id']) or {}
        st.write('Actual original outcome:',action.get('state'))
        if action.get('undo_request_key'):st.info('This action passed verification and was later restored by explicit Undo. Undo is separate from a failed verification rollback.')
        table([{'Verification':i+1,'RTT mean (ms)':p['window']['features'].get('rtt_mean_ms'),'Critical delivery (bps)':p['window']['features'].get('critical_goodput_bps'),
            'Loss fraction':p['window']['features'].get('udp_loss_fraction'),'Passed':p.get('evaluation',{}).get('eligible')} for i,p in enumerate(action.get('post_windows',[]))])
        transient=action.get('transient_disruption') or {};st.caption(transient.get('resolution') or transient.get('reason') or 'Transient loss unmeasured; this does not mean zero.')
        table([{'Flow':k,**v} for k,v in (transient.get('metrics') or {}).items()]);table(refusal_rows(action));raw('Verification, rollback and timing',action)
    if instance:
        undo=read(client,'/v1/dashboard/reversible/'+instance) or {};st.caption(undo.get('reason','Undo applicability unavailable'))
        undo_key='demo_u'+st.session_state.setdefault('v4_undo_suffix',uuid4().hex)
        operation(client,'v4_undo','Undo kept laboratory action','/v1/lab/undo',{'instance_id':instance,'action_id':undo.get('action_id'),
            'request_key':undo_key},disabled=blocked or not undo.get('available'),destructive=True)
    with st.expander('Recent audit history'):table(records(client,'audit'))


def results(client,status,host):
    del host
    st.title('Results');st.caption('Current backend, historical experiments, the prospective cohort and software checks are separate evidence scopes.')
    if status:
        st.subheader('Connected backend dataset and active model')
        table([{'Partition':k,'Accepted windows':v} for k,v in status['dataset']['counts_by_split'].items()]);table(status['dataset']['batches'])
        st.write('Active model:',status['models'].get('active_model_id') or 'None')
        model=read(client,'/v1/models') or {}
        with st.expander('Model versions and supported domains'):raw('Trusted registry',model)
    items=(read(client,'/v1/dashboard/evidence') or {}).get('records',[])
    for item in items:
        if not item['available']:continue
        data=read(client,'/v1/dashboard/evidence/'+item['artifact_id'])
        if not data:continue
        r=data['evidence']
        if item['artifact_id'] in {'completion3','completion4','evaluation'}:
            st.subheader(item['title']);st.write('Recorded status:',r.get('status','See evidence'))
            if item['artifact_id']=='completion3':
                cohort=r.get('dataset_audit',{}).get('cohort') or {}
                table([{'Accepted':r.get('accepted_windows'),'Target':r.get('expected_windows'),'Episodes':r.get('completed_episodes'),
                    'Represented families':cohort.get('represented_families'),'Ready':r.get('dataset_ready')}]);table([{'Class':k,'Windows':v} for k,v in cohort.get('class_counts',{}).items()])
                table([{'Partition':k,'Windows':v} for k,v in r.get('partitions',{}).items()])
            metrics=r.get('held_out_metrics') or {}
            if metrics:
                table([{'Windows':metrics.get('windows'),'Episodes':metrics.get('episodes'),'Families':metrics.get('families'),
                    'RF argmax macro F1':metrics.get('window_classification',{}).get('macro_f1'),'Operational coverage':metrics.get('abstention',{}).get('coverage_fraction')}])
                table([{'Metric':k,'Value':v} for k,v in metrics.get('calibration',{}).items() if not isinstance(v,(list,dict))])
                st.write('Threshold detection:',metrics.get('rule_baseline'));st.write('IF ranking:',metrics.get('IF_ranking'));st.write('No-XAI:',metrics.get('no_XAI'))
            elif item['artifact_id']=='completion3':st.info('New frozen held-out metrics, calibration, IF/SHAP and no-XAI remain pending.')
            for key,label in [('baseline_results','Baseline comparisons'),('scale_results','5/10/15-switch measurements')]:
                values=r.get(key)
                if values:
                    st.markdown('**'+label+'**');table([{k:v for k,v in row.items() if not isinstance(v,(dict,list))} for row in values])
                elif item['artifact_id']=='completion3':st.caption(label+': pending; no replacement values.')
            if r.get('per_fault'):
                with st.expander('Four-fault fidelity, candidate and recovery coverage',expanded=True):
                    for fault,value_ in r['per_fault'].items():st.write(fault);table(value_ if isinstance(value_,list) else [value_])
            if r.get('blockers'):st.warning('\n\n'.join(r['blockers']))
        with st.expander(item['title']+' · approved evidence'):
            st.caption(item['kind']);st.download_button('Download approved evidence',json.dumps(data,indent=2),
                file_name='explainnet-'+item['artifact_id']+'.json',mime='application/json',key='v4_download_'+item['artifact_id']);raw('Technical evidence',r)
    st.subheader('Report and presentation downloads')
    downloads=(read(client,'/v1/dashboard/deliverables') or {}).get('records',[])
    for file in downloads:
        st.link_button(file['title'],client.settings.api_url+'/v1/dashboard/deliverables/'+file['id'])
    if not downloads:st.caption('Approved current-edition deliverables are not available yet.')
    with st.expander('Architecture, scope, glossary and team'):
        st.write('Streamlit → unprivileged API → SQLite evidence and UID-bound privileged agent → isolated original/twin dataplanes.')
        st.write('Original review scope: emulated faults, IF/RF/SHAP, observable reconstruction, candidate comparison and evaluation. Assisted/automatic original-lab actuation is a later extension. Production-network automatic remediation is outside scope.')
        table([{'Term':k,'Meaning':v} for k,v in [('Fidelity','Measured original/twin agreement with unchanged residual/quality gates'),('SHAP','Per-event raw RF probability contributions'),('Observed-only','Explicit rules/measurements laboratory workflow; not trained-model recovery'),('Decision time','Complete declared decision boundary, not inference alone')]])
        st.write('Visweswar Sarma · [registration redacted]');st.write('Shafin Khan · [registration redacted]');st.write('Anushka Jain · [registration redacted]')


def render(index,client=None):
    client=client or ApiClient();status=read(client,'/v1/dashboard/status')
    slot=st.session_state.get('_shell_status_slot')
    if slot is not None:
        from explainnet.dashboard.shell import status_panel
        with slot.container():
            if not status_panel(client,status,read):return
    host=read(client,'/v1/demo/host-status') or {'active':True,'reason':'Shared laboratory readiness could not be verified. Mutation controls are withheld.'}
    if status and status['control'].get('allow_observed_only'):st.warning('OBSERVED-ONLY LAB PROFILE: rules/measurements are not trained IF/RF/SHAP recovery.')
    [live,diagnosis,twin_recovery,results][index](client,status,host)
    activity(client);st.caption('ExplainNet Twin · local owned laboratory only · timestamps UTC · missing values remain unavailable')


def render_selected(index):
    interval='10s' if st.session_state.get('refresh_active_view',False) else None
    st.fragment(run_every=interval)(lambda:render(index))()
