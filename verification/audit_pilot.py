"""Read-only, offline audit of a completed or terminally aborted FINAL pilot.

Usage: python audit_pilot.py PROJECT_ROOT RESULT_FOLDER OUTPUT_JSON
The physical replay below does not call scm.engine. The saved-metric comparison
separately uses the source in PROJECT_ROOT. No API requests or result edits occur.
"""
from argparse import ArgumentParser
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import sys


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def deep_differences(expected, observed, path='$'):
    if isinstance(expected, dict) and isinstance(observed, dict):
        result=[]
        for key in sorted(set(expected)|set(observed)):
            if key not in expected or key not in observed:
                result.append({'path':path+'.'+key,'kind':'missing_key'})
            else:
                result.extend(deep_differences(expected[key],observed[key],path+'.'+key))
        return result
    if isinstance(expected,list) and isinstance(observed,list):
        if len(expected)!=len(observed):
            return [{'path':path,'kind':'length','expected':len(expected),'observed':len(observed)}]
        return [d for i,(a,b) in enumerate(zip(expected,observed)) for d in deep_differences(a,b,f'{path}[{i}]')]
    if expected!=observed:
        return [{'path':path,'kind':'value','expected':expected,'observed':observed}]
    return []


def usage_summary(events):
    result={'physical_attempts':len(events),
            'retry_attempts':sum(e.get('attempt',0)>0 for e in events),
            'failed_attempts':sum(e.get('success') is False for e in events),
            'format_failure_attempts':sum(bool(e.get('format_failure')) for e in events),
            'error_types':dict(Counter(e['error_type'] for e in events if e.get('error_type')))}
    for field in ('input_tokens','output_tokens','total_tokens','reported_cost_usd'):
        values=[e.get(field) for e in events]
        known=[v for v in values if v is not None]
        result[field]={'total':sum(known) if len(known)==len(values) else None,
                       'known_subtotal':sum(known),'reported_attempts':len(known),
                       'missing_attempts':len(values)-len(known),
                       'coverage':len(known)/len(values) if values else 1.0}
    return result


def audit(project_root, result_folder):
    project=Path(project_root).resolve();root=Path(result_folder).resolve()
    # Defense in depth: even a mistaken future import or call cannot use the API.
    def denied(*args,**kwargs):
        raise RuntimeError('Network is disabled in the read-only pilot audit')
    socket.socket.connect=denied
    socket.socket.connect_ex=denied
    socket.create_connection=denied
    os.environ.pop('OPENROUTER_API_KEY',None)
    sys.path.insert(0,str(project))
    from scm.config import SimulationConfig, canonical_hash, ROLES
    from scm.metrics import summarize, _usage
    from run_qmean import QMEAN
    batch=read(root/'batch_manifest.json')
    config=SimulationConfig(**batch['simulation'])
    conditions={c['id']:c for c in batch['conditions']}
    expected={(c,s) for c in conditions for s in batch['seeds']}
    checks=Counter();failures=[];warnings=[];episode_reports=[];all_m2=[];m2_rows=[]
    m2_request_keys=set();m2_retried_request_keys=set()
    physical_count=Counter();warmups={};seen=set();source_files={}

    def check(ok,name,where,details=None):
        checks[name]+=1
        if not ok: failures.append({'check':name,'where':where,'details':details})

    def equal(a,b,name,where):
        delta=deep_differences(a,b)
        check(not delta,name,where,delta)
        return delta

    check(Path(sys.modules['scm.metrics'].__file__).resolve().is_relative_to(project),
          'requested_project_imported',str(project))
    check(config.safety_stock==10,'safety_stock_10','batch',config.safety_stock)
    check(config.lead_time==2,'lead_time_two','batch')
    check(config.initial_inventory==0,'initial_inventory_zero','batch')
    check(len(expected)==len(batch['conditions'])*len(batch['seeds']),'unique_batch_registration','batch')
    scm_text={p.name:p.read_text(encoding='utf-8') for p in sorted((project/'scm').glob('*.py'))}
    current_source=canonical_hash(scm_text)
    for p in sorted((project/'scm').glob('*.py')):
        source_files['scm/'+p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
    intervention=None
    if (root/'intervention_manifest.json').exists():
        intervention=read(root/'intervention_manifest.json')
        sig=intervention['signature']
        check(canonical_hash(sig)==intervention['signature_hash'],'intervention_manifest_hash','batch')
        check(sig['scm_source_hash']==current_source,'current_source_matches_run','batch')
        runtime_hash=canonical_hash({'scm_source_hash':current_source,'intervention':sig['intervention']})
        check(runtime_hash==batch['source_hash']==sig['runtime_source_hash'],'runtime_source_hash','batch')
        check(sig['simulation']==batch['simulation'],'intervention_simulation_matches_batch','batch')
        check(sig['intervention']['q_base_meaning_sentence']==QMEAN,'qmean_intervention_registered','batch')
    else:
        check(current_source==batch['source_hash'],'current_source_matches_run','batch')
        warnings.append('No intervention manifest: CMT order prompts are still checked for the required Q_base sentence.')

    def initial():
        return [{'I':config.initial_inventory,'B':config.initial_backlog,
                 'P':config.initial_arrival*config.lead_time,
                 'arrivals':{t:config.initial_arrival for t in range(1,config.lead_time+1)}} for _ in ROLES]

    def begin(states,i,t,demand):
        state=states[i]
        arrival=state['arrivals'].pop(t,0)
        prior_i,prior_b,prior_p=state['I'],state['B'],state['P']
        shipped=min(prior_i+arrival,prior_b+demand)
        expected_row={'D':demand,'A':arrival,'X':shipped,'I':prior_i+arrival-shipped,
                      'B':prior_b+demand-shipped,'P_pre':prior_p-arrival,'B_previous':prior_b,
                      'immediate_filled':min(demand,max(0,shipped-prior_b))}
        state.update(I=expected_row['I'],B=expected_row['B'],P=expected_row['P_pre'])
        if i and shipped:
            due=t+config.lead_time
            states[i-1]['arrivals'][due]=states[i-1]['arrivals'].get(due,0)+shipped
        return expected_row

    def replay(rows, states, demand, first, where, partial=False, planned=None):
        ordered=sorted(rows,key=lambda r:(r['t'],r['agent']))
        check(ordered==rows,'physical_rows_ordered',where)
        target=[(first+k//4,k%4) for k in range(len(rows))]
        check([(r['t'],r['agent']) for r in ordered]==target,'contiguous_unique_physical_prefix',where)
        if not partial:
            check(len(rows)==4*planned,'complete_physical_grid',where,{'actual':len(rows),'expected':4*planned})
        last_q={};period_end_checks=0
        for row in ordered:
            t,i=row['t'],row['agent'];tag=f'{where}:t{t}:{ROLES[i]}'
            incoming=demand[t-1] if i==0 else last_q.get((t,i-1))
            if incoming is None:
                check(False,'downstream_current_order_present',tag);continue
            old_i=states[i]['I']
            expected_row=begin(states,i,t,incoming)
            for key,value in expected_row.items():
                check(row.get(key)==value,'physical_'+key,tag,{'expected':value,'observed':row.get(key)})
            check(row['role']==ROLES[i],'physical_role',tag)
            check(0<=row['X']<=old_i+row['A'],'shipment_within_available',tag)
            check(all(type(row[k]) is int and row[k]>=0 for k in ('I','B','D','A','X','P_pre','P_post')),
                  'physical_nonnegative_integers',tag)
            check(not(row['I']>0 and row['B']>0),'no_unfilled_demand_while_stock_remains',tag)
            q=row['Q_final']
            check(type(q)is int and 0<=q<=config.order_cap,'actual_order_integer_in_range',tag,q)
            states[i]['P']+=q
            check(row['P_post']==states[i]['P'],'physical_P_post',tag)
            if i==3 and q:
                due=t+config.lead_time
                states[i]['arrivals'][due]=states[i]['arrivals'].get(due,0)+q
            costs={'holding_cost':states[i]['I']*config.holding_cost,'backlog_cost':states[i]['B']*config.backlog_cost,
                   'variable_order_cost':q*config.variable_order_cost,'fixed_order_cost':config.fixed_order_cost if q else 0}
            for key,value in costs.items():check(row.get(key)==value,'physical_'+key,tag)
            for key in ('cost','local_cost','total_cost'):check(row.get(key)==sum(costs.values()),'physical_'+key,tag)
            last_q[(t,i)]=q
            if i==3:
                for j,state in enumerate(states):
                    supplier_backlog=states[j+1]['B'] if j<3 else 0
                    check(state['P']==sum(state['arrivals'].values())+supplier_backlog,
                          'period_end_outstanding_equals_transit_plus_supplier_backlog',f'{where}:t{t}:{ROLES[j]}')
                    period_end_checks+=1
        return states,last_q,period_end_checks

    for seed in batch['seeds']:
        cache=read(root/'warmup'/f'seed-{seed}.json')
        check(cache['seed']==seed,'warmup_seed',str(seed))
        check(canonical_hash(cache['snapshot'])==cache['snapshot_hash'],'warmup_snapshot_hash',str(seed))
        check(canonical_hash(cache['demand'])==cache['demand_hash'],'demand_hash',str(seed))
        check(canonical_hash(batch['simulation'])==cache['config_hash'],'warmup_config_hash',str(seed))
        check(cache['source_hash']==batch['source_hash'],'warmup_source_hash',str(seed))
        rows=sorted([r for a in cache['snapshot']['agents'] for r in a['history']],key=lambda r:(r['t'],r['agent']))
        states,_,_=replay(rows,initial(),cache['demand'],1,f'warmup:{seed}',planned=config.warmup_periods)
        for i,state in enumerate(states):
            saved=cache['snapshot']['agents'][i]
            check(all(state[k]==saved[k] for k in ('I','B','P')) and state['arrivals']=={int(k):v for k,v in saved['arrivals'].items()},
                  'warmup_manual_terminal_matches_snapshot',f'{seed}:{ROLES[i]}')
        cache['manual_state']=states;warmups[seed]=cache;physical_count['common_warmup_rows']+=len(rows)

    aggregate={(r['condition'],r['seed']):r for r in read(root/'results.json')} if (root/'results.json').exists() else {}
    order_prompt_contracts=defaultdict(dict)
    for folder in sorted((root/'episodes').iterdir()):
        if not folder.is_dir():continue
        if not (folder/'summary.json').exists():
            warnings.append(f'No terminal summary: {folder.name}');continue
        result=read(folder/'summary.json');name=result['condition'];seed=result['seed'];key=(name,seed)
        check(key in expected and key not in seen,'episode_registered_unique',folder.name);seen.add(key)
        condition=conditions[name];cache=warmups[seed]
        is_abort=result.get('status')=='aborted'
        check(folder.name==f'{name}__{result["objective"]}__seed-{seed}','episode_folder_identity',folder.name)
        check(result['source_hash']==batch['source_hash'] and result['variant']==batch['variant'],'episode_source_variant',folder.name)
        check(result['warmup_hash']==cache['snapshot_hash'] and result['demand_hash']==cache['demand_hash'],'episode_shared_warmup_and_demand',folder.name)
        check(result==aggregate.get(key),'episode_summary_equals_results_json',folder.name)
        manifest=read(folder/'manifest.json')
        check(manifest['signature']['config']==batch['simulation'] and manifest['signature']['api']==batch['api'],
              'episode_simulation_and_api',folder.name)
        rows=read(folder/('partial_periods.json' if is_abort else 'periods.json'))
        states,last_q,period_end_checks=replay(rows,deepcopy(cache['manual_state']),cache['demand'],config.warmup_periods+1,
                                               folder.name,partial=is_abort,planned=config.evaluation_periods)
        physical_count['committed_evaluation_rows']+=len(rows)
        physical_count['completed_period_end_role_checks']+=period_end_checks
        snapshot_doc=read(folder/('abort_snapshot.json' if is_abort else 'checkpoint.json'))
        check(snapshot_doc['signature_hash']==canonical_hash(manifest['signature']),'checkpoint_signature',folder.name)
        snapshot=snapshot_doc['environment'];pending=snapshot.get('pending')
        if pending:
            t,i=pending['t'],pending['agent']
            incoming=cache['demand'][t-1] if i==0 else last_q.get((t,i-1))
            expected_pending=begin(states,i,t,incoming)
            for field,value in expected_pending.items():
                check(pending['row'].get(field)==value,'pending_physical_'+field,folder.name)
            check('Q_final' not in pending['row'],'pending_order_uncommitted',folder.name)
        for i,state in enumerate(states):
            saved=snapshot['agents'][i]
            check(all(state[k]==saved[k] for k in ('I','B','P')) and state['arrivals']=={int(k):v for k,v in saved['arrivals'].items()},
                  'snapshot_matches_manual_physics',f'{folder.name}:{ROLES[i]}')
            check(saved['history'][:config.warmup_periods]==cache['snapshot']['agents'][i]['history'],
                  'checkpoint_preserves_common_warmup',f'{folder.name}:{ROLES[i]}')
        snapshot_rows=sorted([r for a in snapshot['agents'] for r in a['history'] if r['t']>config.warmup_periods],key=lambda r:(r['t'],r['agent']))
        check(snapshot_rows==rows,'snapshot_committed_rows_match_file',folder.name)
        events=[]
        if (folder/'api_calls.jsonl').exists():
            with (folder/'api_calls.jsonl').open(encoding='utf-8') as f:
                events=[json.loads(line) for line in f if line.strip()]
        elif (folder/'mock_calls.json').exists():events=read(folder/'mock_calls.json')
        route_counter=Counter();identities=set()
        for index,event in enumerate(events):
            tag=f'{folder.name}:attempt{index}'
            check(event['condition']==name and event['objective']==condition['objective'] and event['role']==ROLES[event['agent']],
                  'event_identity',tag)
            attempt_key=(event['t'],event['agent'],event['task'],event.get('attempt',0))
            check(attempt_key not in identities,'unique_event_attempt',tag);identities.add(attempt_key)
            if result['backend']=='openrouter' and event.get('success'):
                actual=(event.get('actual_model'),event.get('actual_provider'),event.get('actual_service_tier'))
                route_counter[actual]+=1
                check(actual==(batch['api']['model'],'Google AI Studio',batch['api']['service_tier']),
                      'successful_actual_model_provider_tier',tag,list(actual))
            if event['task']=='order':
                cmt=name.startswith('C')
                has_qmean=QMEAN in event['instructions']
                check(has_qmean==cmt,'qmean_CMT_only',tag,{'present':has_qmean,'expected':cmt})
                if condition.get('direct_order'):
                    check('Q_base' not in event['payload'] and 'M' not in event['payload'],'direct_order_no_current_support_or_message',tag)
                if condition.get('minimal_prompt'):
                    check(set(event['payload'])-{'retry_feedback'}=={'C','D'},'minimal_input_C_D_only',tag)
                    if 'response_schema' in event:
                        contract=(event['instructions'],event['response_schema'])
                        prior=order_prompt_contracts[event['role']].setdefault(name,contract)
                        check(prior==contract,'minimal_contract_stable_within_role',tag)
            if condition['m']=='M2' and event['task']=='message':
                all_m2.append(event)
                message_key=(name,seed,event['t'],event['agent'])
                m2_request_keys.add(message_key)
                if event.get('attempt',0)>0:m2_retried_request_keys.add(message_key)
        failed=[e for e in events if e.get('success') is False]
        usage=usage_summary(events)
        no_recovery=condition.get('no_recovery',False)
        if no_recovery:
            check(all(e.get('attempt',0)==0 and e.get('effective_max_retries')==0 for e in events),'G0_zero_retry_policy',folder.name)
            check(all(r.get('correction_count',0)==0 and r.get('fallback_count',0)==0 and r.get('retry_count',0)==0 for r in rows),
                  'G0_zero_correction_fallback_retry_rows',folder.name)
            check(all(r['Q_final']==r['Q_final_raw'] and type(r['Q_final'])is int for r in rows),'G0_value_preserving_canonical_integer',folder.name)
            check(not failed or (is_abort and len(failed)==1 and events[-1] is failed[0]),'G0_first_failure_is_terminal',folder.name)
        metric_comparison={'scope':'complete_horizon_only','performed':not is_abort}
        if is_abort:
            check(result['complete'] is False and result.get('terminal') is True and result['metrics']=={},'abort_has_no_completed_metrics',folder.name)
            check(snapshot_doc.get('resume_allowed') is False and snapshot_doc.get('terminal') is True,'abort_snapshot_not_resumable',folder.name)
            check(not (folder/'periods.json').exists(),'abort_partial_records_separate',folder.name)
            partial=result['partial_metrics']
            check(partial.get('full_horizon_comparable') is False,'abort_not_full_horizon_comparable',folder.name)
            check(partial['committed_agent_periods']==len(rows) and partial['partial_realized_cost']==sum(r['cost'] for r in rows),
                  'partial_cost_and_count_recomputed',folder.name)
            partial_delta=equal(_usage(events),partial['usage'],'partial_usage_recomputed_exact',folder.name)
            metric_comparison.update(full_metrics_empty=True,partial_usage_exact=not partial_delta)
        else:
            check(result['complete'] is True,'complete_result_status',folder.name)
            recalculated=summarize(rows,events,config)
            delta=equal(recalculated,result['metrics'],'saved_metrics_recomputed_exact',folder.name)
            metric_comparison.update(exact_match=not delta,mismatches=delta)
        if condition['m']=='M2':
            sender_rows=[r for r in rows if r['agent']<3]
            m2_rows.extend(sender_rows)
            check(all(bool(r.get('outgoing_message'))!=bool(r.get('message_fallback')) for r in sender_rows),
                  'M2_success_or_empty_fallback',folder.name)
        episode_reports.append({'condition':name,'seed':seed,'status':result.get('status','completed'),
             'backend':result['backend'],'rows':len(rows),'planned_rows':config.evaluation_periods*4,
             'physical_replay':'independent_from_scm_engine','metric_comparison':metric_comparison,
             'no_recovery':no_recovery,'abort':result.get('abort'),'usage':usage,
             'route_verification':'verified_successful_api_calls' if result['backend']=='openrouter' else 'not_applicable_mock',
             'routes':[{'model':key[0],'provider':key[1],'tier':key[2],'calls':value} for key,value in route_counter.items()],
             'terminal_or_abort_state':{ROLES[i]:{'I':state['I'],'B':state['B'],'P':state['P'],
                                         'transit':sum(state['arrivals'].values())} for i,state in enumerate(states)}})
    check(seen==expected,'all_registered_trials_terminal','batch',{'missing':sorted(expected-seen),'unexpected':sorted(seen-expected)})
    for role,contracts in order_prompt_contracts.items():
        if 'N0' in contracts and 'N0-G0' in contracts:
            check(contracts['N0']==contracts['N0-G0'],'N0_G0_identical_prompt_schema',role)
    m2={'logical_message_requests':len(m2_request_keys),
        'requests_with_retry':len(m2_retried_request_keys),
        'committed_sender_opportunities':len(m2_rows),
        'forwarded_nonempty_messages':sum(isinstance(r.get('outgoing_message'),str) and bool(r['outgoing_message'].strip()) for r in m2_rows),
        'empty_fallback_messages':sum(bool(r.get('message_fallback')) for r in m2_rows),
        'message_attempt_usage':usage_summary(all_m2),
        'semantic_correctness':'Not established by this audit; message presence/format/retry/usage are operational counts.'}
    return {'audit_scope':'Current FINAL pilot; no API calls; no original result/settings/source edits',
            'project_root':str(project),'result_folder':str(root),'network_disabled':True,
            'source_files_sha256':source_files,'metric_module':sys.modules['scm.metrics'].__file__,
            'simulation':asdict(config),'api_configuration':batch['api'],
            'registered_trials':len(expected),'terminal_results_found':len(seen),
            'checks':dict(checks),'checks_total':sum(checks.values()),'physical_counts':dict(physical_count),
            'passed':not failures,'failure_count':len(failures),'failures':failures,'warnings':warnings,
            'm2':m2,'episodes':episode_reports,
            'limitations':['A successful mechanical audit does not establish forecast quality, optimal ordering or causal treatment effects.',
                           'Aborted partial costs must not be ranked against full-horizon completed costs.',
                           'The same-source metric comparison checks reproducibility of the defined metrics; physical replay is independently coded.',
                           'Mock output verifies execution structure only, not LLM performance.']}


def main():
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('project_root',type=Path)
    parser.add_argument('result_folder',type=Path)
    parser.add_argument('output_json',type=Path)
    args=parser.parse_args()
    output=args.output_json.resolve()
    result_root=args.result_folder.resolve()
    if output.suffix.lower()!='.json':parser.error('output_json must have a .json extension.')
    if output.is_relative_to(result_root):
        parser.error('Write the audit outside the original result folder.')
    result=audit(args.project_root,args.result_folder)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'checks':result['checks_total'],
                      'failures':result['failure_count'],'trials':result['terminal_results_found'],
                      'output':str(output)},ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
