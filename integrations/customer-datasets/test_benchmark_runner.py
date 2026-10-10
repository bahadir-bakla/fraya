"""Offline network/clock mocks only. No Freya simulations or workflow writes."""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import benchmark_adapter as b
import benchmark_runner as r


def rows(count=1):
    result = []
    for style in list(b.official.STYLES)[:count]:
        case = copy.deepcopy(b.PUBLIC["PUB-01"])
        case.update(variant_id="PUB-01__" + style, style=style, delivery_profile="plain",
                    local_only=False, hosted_registered=True, execution_status="not_executed")
        result.append(case)
    if count > len(result):
        for profile in list(b.PROFILES)[1:count - len(result) + 1]:
            case = copy.deepcopy(b.PUBLIC["PUB-01"])
            case.update(variant_id="PUB-01__" + profile, style=None, delivery_profile=profile,
                        local_only=False, hosted_registered=True, execution_status="not_executed")
            result.append(case)
    b.validate_hosted(result)
    return result


def hosted_ledger(case, customer_id):
    """Mock receipt with official hosted args shape; not an execution artifact."""
    ledger = copy.deepcopy(case["expected"])
    products = [{"product_id": "p" + str(i + 1), **p} for i, p in enumerate(case["products"])]
    calls = [{"tool": "verify_identity", "args": {"field": field, "answer": answer},
              "result": {"ok": True, "verified": True, "wrong_answers_left": 3,
                         "all_verified": index == 1}}
             for index, (field, answer) in enumerate(case["identity"].items())]
    calls.append({"tool": "get_account", "args": {}, "result": {"ok": True, "products": products}})
    for promise in ledger["promises"]:
        calls.append({"tool": "create_promise", "args": copy.deepcopy(promise), "result": {"ok": True}})
    calls.append({"tool": "close_call", "args": {"outcome": ledger["outcome"]}, "result": {"ok": True}})
    ledger.update(calls=calls, customer_id=customer_id, case=case["id"], now=case["variables"]["now"])
    return ledger


class FakeClock:
    def __init__(self):
        self.now = 0
        self.waits = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


class FakeClient:
    AGENT_LLM = r.AGENT_MODEL
    SIM_LLM = {"provider": "google", "model": "gemini-3-flash-preview"}
    URL = "https://test-freya.invalid"
    HOST = "https://test-bank.invalid"

    def __init__(self, cases):
        self.cases = {case["id"]: case for case in cases}
        self.requests, self.starts, self.sessions, self.simulations = [], [], {}, {}
        self.next_customer, self.next_persona = 0, 0
        self.external_status = None
        self.duplicate_customer = False
        self.sim_status = "completed"
        self.outcomes = []
        self.bad_total = False
        self.duplicate_judge = False
        self.no_call_id = False
        self.bad_ledger = None
        self.bad_call_agent = False
        self.bad_call_customer = False
        self.blank_call_evidence = False
        self.corrupt_call_receipt = False
        self.extra_session_field = False
        self.start_error = None
        self.extra_workspace_page = False
        self.version_drift = False

    def workspace_id(self):
        return "ws_test"

    def bank(self, path, body=None):
        self.requests.append(("POST" if body is not None else "GET", path, copy.deepcopy(body), {}))
        if path == "/v1/practice/sessions":
            self.next_customer += 1
            cid = "c_test_1" if self.duplicate_customer else "c_test_" + str(self.next_customer)
            case = self.cases[body["case"]]
            self.sessions[cid] = case
            variables = {**case["variables"], "customer_id": cid}
            if self.extra_session_field:
                variables["expected"] = case["expected"]
            return {"variables": variables}
        cid = path.rsplit("/", 1)[-1]
        ledger = hosted_ledger(self.sessions[cid], cid)
        if self.bad_ledger:
            ledger[self.bad_ledger[0]] = self.bad_ledger[1]
        return ledger

    def api(self, method, path, body=None, **params):
        self.requests.append((method, path, copy.deepcopy(body), params))
        if method == "POST" and path == "/api/v2/personas":
            self.next_persona += 1
            return {"personas": [{"id": "persona_" + str(self.next_persona)}]}
        if method == "POST" and path == "/api/v2/simulations":
            self.starts.append(copy.deepcopy(body))
            if self.start_error:
                raise RuntimeError(self.start_error)
            sid = "sim_" + str(len(self.starts))
            self.simulations[sid] = copy.deepcopy(body)
            return {"simulation": {"id": sid}}
        if path == "/api/v2/simulations":
            if self.extra_workspace_page and params["offset"] == 0:
                return {"simulations": [{"id": f"historic_{i}", "status": "completed"} for i in range(params["limit"])]}
            if self.external_status:
                return {"simulations": [{"id": "someone_else", "status": self.external_status}]}
            return {"simulations": [{"id": sid, "status": "completed"} for sid in self.simulations]}
        parts = path.split("/")
        if path.startswith("/api/v2/call/"):
            cid = parts[-1]
            sid=next(key for key in self.simulations if cid.startswith('call_'+key+'_'))
            pid=cid[len('call_'+sid+'_'):]
            customer=self.simulations[sid]['customerVariablesMap'][pid]['customer_id']
            ledger=hosted_ledger(self.sessions[customer],customer)
            messages=[{'role':'assistant','message':'UNIT TEST SYNTHETIC ASSISTANT'}]
            for bank_call in ledger['calls']:
                body={**bank_call['args'],'customer_id':'different_customer' if self.bad_call_customer else customer}
                start={'event':'function_call_start','function':'api_call','args':{'url':b.local.API['servers'][0]['url'].rstrip('/')+'/'+bank_call['tool'],'method':'POST','body':body}}
                complete={'event':'function_call_complete','function':'api_call','result':{'data':copy.deepcopy(bank_call['result'])}}
                if self.corrupt_call_receipt:complete['result']['data']['ok']=False
                messages+=[{'role':'system','message':json.dumps(start)},{'role':'system','message':json.dumps(complete)}]
            call = {"id": cid,'assistantId':self.simulations[sid]['agentId'],'workspaceId':'ws_test',
                    'assistantWorkflowId':'mock_workflow','entityVersionId':'mock_version',
                    'entityVersionNumber':8 if self.version_drift and sid!='sim_1' else 7,
                    "messages": [{'role':'user','message':'UNIT TEST MOCK ONLY'}] if self.blank_call_evidence else messages}
            if self.bad_call_agent:
                call["agentId"] = "different_agent"
            return {"call": call}
        sid = parts[4]
        if path.endswith("/iterations"):
            return {"iterations": [{"id": "iteration_" + sid}]}
        if "/iterations/" in path:
            pids = self.simulations[sid]["selectedPersonaIds"]
            number = int(sid.rsplit("_", 1)[-1])
            outcome = self.outcomes[number - 1] if len(self.outcomes) >= number else "pass"
            runs = [{"personaId": pid, "callId": f"call_{sid}_{pid}", "outcome": outcome,
                     "reason": "mock verdict"} for pid in pids]
            if self.duplicate_judge and len(runs) > 1:
                runs[-1]["personaId"] = runs[0]["personaId"]
            if self.no_call_id:
                runs[0].pop("callId")
            return {"runs": runs, "runsTotal": len(runs) + int(self.bad_total)}
        return {"simulation": {"id": sid, "status": self.sim_status}}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clock = FakeClock()
        # Real persona construction and strict scorer; pack-verification mock only
        # avoids coupling mocked execution to a concurrently rebuilt parent pack.
        self.adapter = SimpleNamespace(KIT=b.KIT, PUBLIC=b.PUBLIC,
                                       validate_hosted=b.validate_hosted, persona_for=b.persona_for,
                                       score=b.score, verify_pack=Mock(return_value=None))

    def execute(self, cases=None, client=None, **options):
        cases = cases or rows()
        client = client or FakeClient(cases)
        with patch("urllib.request.urlopen", side_effect=AssertionError("real network forbidden")):
            result = r.execute(cases, self.adapter, agent_id="agent_test", brief="A",
                               only=",".join(case["variant_id"] for case in cases),
                               pack_path=None, output_root=self.root,
                               client=client, clock=self.clock.clock, sleep=self.clock.sleep, **options)
        manifest = json.loads((Path(result["run_dir"]) / "manifest.json").read_text(encoding="utf-8"))
        return result, manifest, client

    def test_keyless_dry_plan_no_network_no_artifacts(self):
        pack = self.root / "pack.json"
        pack.write_text(json.dumps(rows()), encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True), patch("urllib.request.urlopen", side_effect=AssertionError), patch("sys.stdout", new_callable=io.StringIO) as stdout:
            exit_code = r.main(["--cases", str(pack), "--out", str(self.root / "never_created")], adapter=self.adapter)
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["execution_status"], "not_executed")
        self.assertFalse((self.root / "never_created").exists())
        self.adapter.verify_pack.assert_not_called()

    def test_fail_fast_preserves_failed_batch_and_unverified_repeats(self):
        cases=rows(2);client=FakeClient(cases);client.outcomes=['fail']
        result,manifest,client=self.execute(cases=cases,client=client,fail_fast=True)
        self.assertEqual(result['execution_status'],'stopped_on_failure')
        self.assertFalse(result['pass'])
        self.assertEqual(len(client.starts),1)
        self.assertEqual(sum(j['state']=='scored' for j in manifest['jobs']),2)
        for row in result['final']:
            self.assertTrue(row['failure_observed'])
            self.assertEqual(row['completed_repetitions'],1)
            self.assertEqual(row['pending_repetitions'],2)
            self.assertFalse(row['pass'])

    def test_runner_source_change_is_rejected_before_any_network(self):
        client=FakeClient(rows())
        with patch.object(r,'RUNNER_SOURCE_PIN','different-source'):
            with self.assertRaisesRegex(r.RunnerError,'pack_integrity_failed'):
                self.execute(client=client)
        self.assertEqual(client.requests,[])

    def test_parallel_repeats_share_capacity_but_never_sessions_or_personas(self):
        cases=rows(2)
        result,manifest,client=self.execute(cases=cases,parallel_reps=True)
        self.assertTrue(result['pass'])
        self.assertEqual([len(x['selectedPersonaIds']) for x in client.starts],[5,1])
        self.assertEqual(len({j['customer_id'] for j in manifest['jobs']}),6)
        self.assertEqual(len({j['persona_id'] for j in manifest['jobs']}),6)
        self.assertEqual([x['completed_repetitions'] for x in result['final']],[3,3])
        self.assertEqual(r.plan(cases,self.adapter,reps=3,batch_size=5,parallel_reps=True)['batches_required'],2)

    def test_boolean_receipt_cannot_impersonate_numeric_value(self):
        self.assertFalse(r.receipt_matches({'amount':True},{'amount':1}))
        self.assertFalse(r.receipt_matches({'verified':1},{'verified':True}))
        self.assertTrue(r.receipt_matches({'amount':1.0,'extra':'hook value'},{'amount':1}))

    def test_three_repetitions_cannot_mix_published_versions(self):
        client=FakeClient(rows());client.version_drift=True
        result,manifest,_=self.execute(client=client)
        self.assertFalse(result['pass'])
        self.assertEqual(result['execution_status'],'incomplete')
        self.assertEqual(result['error_code'],'published_version_changed_during_run')
        self.assertEqual(manifest['tested_version']['published_version_number'],7)

    def test_cli_execute_requires_explicit_selection_agent_and_brief(self):
        for argv in (["--execute"], ["--execute", "--agent-id", "agent_test", "--brief", "A"],
                     ["--execute", "--agent-id", "agent_test", "--only", rows()[0]["variant_id"]]):
            with self.subTest(argv=argv), patch("sys.stdout", new_callable=io.StringIO), patch("urllib.request.urlopen", side_effect=AssertionError):
                self.assertEqual(r.main(argv, adapter=self.adapter), 2)

    def test_unknown_duplicate_and_wrong_brief_selections_rejected(self):
        case = rows()[0]
        for selection in (case["variant_id"] + ",typo", case["variant_id"] + "," + case["variant_id"], ""):
            with self.subTest(selection=selection), self.assertRaises(r.RunnerError):
                r.select_rows([case], self.adapter, "A", selection)
        with self.assertRaises(r.RunnerError):
            r.select_rows([case], self.adapter, "B", case["variant_id"])

    def test_fresh_binding_every_variant_and_repetition(self):
        cases = rows(2)
        original = copy.deepcopy(cases)
        result, manifest, client = self.execute(cases)
        self.assertTrue(result["pass"])
        self.assertEqual(cases, original)
        self.assertEqual(len(manifest["jobs"]), 6)
        self.assertEqual(len({job["customer_id"] for job in manifest["jobs"]}), 6)
        self.assertEqual(len({job["persona_id"] for job in manifest["jobs"]}), 6)
        for body in client.starts:
            self.assertEqual(body["runsPerPersona"], 1)
            self.assertEqual(body['maxRetries'],0)
            for key in ("assistantLlmOverride", "routingLlmOverride", "extractionLlmOverride"):
                self.assertEqual(body[key], r.AGENT_MODEL)
            for variables in body["customerVariablesMap"].values():
                self.assertEqual(set(variables), r.CALL_VARIABLES)
        for job in manifest["jobs"]:
            cid = job["customer_id"]
            simulation = next(body for body in client.starts if job["persona_id"] in body["selectedPersonaIds"])
            self.assertEqual(simulation["customerVariablesMap"][job["persona_id"]]["customer_id"], cid)
            self.assertIn(("GET", "/v1/practice/ledger/" + cid, None, {}), client.requests)
            self.assertTrue(job["result"]["ledger_and_trace_pass"])
            self.assertTrue(job["result"]["transcript_pass"])
            self.assertEqual(job['provenance']['published_version_number'],7)
            self.assertTrue((Path(result["run_dir"]) / job["evidence"]).exists())
        self.assertGreater(self.adapter.verify_pack.call_count, 6)
        for method, path, body, _ in client.requests:
            if path == "/v1/practice/sessions":
                self.assertEqual(body, {"case": "PUB-01"})
            self.assertNotIn(method, {"PUT", "PATCH", "DELETE"})

    def test_green_ledger_and_stub_judge_need_real_call_tool_evidence(self):
        client=FakeClient(rows());client.blank_call_evidence=True
        result,_,_=self.execute(client=client)
        self.assertFalse(result['pass'])
        self.assertEqual(result['error_code'],'call_ledger_evidence_mismatch')

    def test_call_http_customer_must_match_the_actual_bank_session(self):
        client=FakeClient(rows());client.bad_call_customer=True
        result,_,_=self.execute(client=client)
        self.assertFalse(result['pass'])
        self.assertEqual(result['error_code'],'call_session_binding_mismatch')

    def test_bank_receipts_cannot_be_substituted_for_different_call_results(self):
        client=FakeClient(rows());client.corrupt_call_receipt=True
        result,_,_=self.execute(client=client)
        self.assertFalse(result['pass'])
        self.assertEqual(result['error_code'],'call_ledger_evidence_mismatch')

    def test_duplicate_customer_rejected_before_simulation(self):
        client = FakeClient(rows(2)); client.duplicate_customer = True
        result, _, client = self.execute(rows(2), client)
        self.assertEqual(result["error_code"], "duplicate_customer_id")
        self.assertFalse(result["pass"])
        self.assertEqual(client.starts, [])

    def test_all_three_needed_and_failed_conversation_with_green_ledger(self):
        client = FakeClient(rows()); client.outcomes = ["pass", "pass", "fail"]
        result, manifest, _ = self.execute(client=client)
        self.assertFalse(result["pass"])
        self.assertEqual(result["final"][0]["passes"], 2)
        self.assertTrue(manifest["jobs"][-1]["result"]["ledger_and_trace_pass"])
        self.assertFalse(manifest["jobs"][-1]["result"]["transcript_pass"])
        with self.assertRaises(r.RunnerError):
            r.plan(rows(), self.adapter, reps=2)

    def test_reference_without_judge_never_conversation_pass(self):
        case = rows()[0]
        case["_session_customer_id"] = "c_test"
        verdict = b.score(case, hosted_ledger(case, "c_test"))
        self.assertTrue(verdict["ledger_and_trace_pass"])
        self.assertFalse(verdict["pass"])
        self.assertFalse(verdict["transcript_pass"])

    def test_batches_capped_at_five(self):
        result, _, client = self.execute(rows(6))
        self.assertTrue(result["pass"])
        self.assertEqual([len(body["selectedPersonaIds"]) for body in client.starts], [5, 1, 5, 1, 5, 1])
        with self.assertRaises(r.RunnerError):
            r.plan(rows(), self.adapter, batch_size=6)

    def test_pending_workspace_and_unknown_states_do_not_mutate_others(self):
        for status in ("pending", "queued", "running", "paused", "draft", "unknown"):
            with self.subTest(status=status):
                client = FakeClient(rows()); client.external_status = status
                result, _, client = self.execute(client=client)
                self.assertEqual(result["error_code"], "workspace_not_idle")
                self.assertTrue(all(method == "GET" for method, _, _, _ in client.requests))
                self.assertEqual(client.starts, [])

    def test_pending_simulation_on_second_workspace_page(self):
        client = FakeClient(rows()); client.extra_workspace_page = True; client.external_status = "pending"
        result, _, client = self.execute(client=client)
        self.assertEqual(result["error_code"], "workspace_not_idle")
        pages = [params for _, path, _, params in client.requests if path == "/api/v2/simulations"]
        self.assertEqual([params["offset"] for params in pages], [0, 25])
        self.assertEqual([params["limit"] for params in pages], [25, 25])
        self.assertEqual(client.starts, [])

    def test_timeout_global_not_per_batch_preserves_owned_simulation(self):
        client = FakeClient(rows()); client.sim_status = "running"
        result, manifest, client = self.execute(client=client, budget_seconds=21)
        self.assertEqual(result["execution_status"], "timeout")
        self.assertFalse(result["pass"])
        self.assertEqual(self.clock.now, 21)
        self.assertEqual(self.clock.waits, [10, 10, 1])
        self.assertEqual(len(client.starts), 1)
        self.assertEqual(manifest["jobs"][0]["state"], "simulation_started")
        self.assertNotIn("result", manifest["jobs"][0])
        self.assertFalse(any(method in {"PUT", "PATCH", "DELETE"} for method, _, _, _ in client.requests))

    def test_status_cardinality_duplicate_judge_and_callid_fail_closed(self):
        for attribute, value in (("sim_status", "failed"), ("bad_total", True),
                                 ("duplicate_judge", True), ("no_call_id", True)):
            with self.subTest(attribute=attribute):
                client = FakeClient(rows(2)); setattr(client, attribute, value)
                result, manifest, _ = self.execute(rows(2), client)
                self.assertFalse(result["pass"])
                self.assertTrue(all(not job.get("result", {}).get("pass") for job in manifest["jobs"]))

    def test_ledger_case_now_customer_and_call_agent_binding(self):
        for field, value in (("case", "PUB-02"), ("now", "2026-10-15T11:00"), ("customer_id", "c_other")):
            with self.subTest(field=field):
                client = FakeClient(rows()); client.bad_ledger = (field, value)
                result, _, _ = self.execute(client=client)
                self.assertFalse(result["pass"])
                self.assertIn("binding_mismatch", result["error_code"])
        client = FakeClient(rows()); client.bad_call_agent = True
        self.assertEqual(self.execute(client=client)[0]["error_code"], "call_binding_mismatch")

    def test_session_cannot_leak_oracle_into_phone_agent(self):
        client = FakeClient(rows()); client.extra_session_field = True
        result, _, client = self.execute(client=client)
        self.assertEqual(result["error_code"], "malformed_session_variables")
        self.assertEqual(client.starts, [])

    def test_uncertain_start_not_retried_and_error_body_withheld(self):
        secret = "UNIT_TEST_SECRET_NOT_A_REAL_KEY"
        client = FakeClient(rows()); client.start_error = "private error body " + secret
        result, manifest, client = self.execute(client=client, secrets=(secret,))
        self.assertEqual(len(client.starts), 1)
        self.assertEqual(manifest["batches"][0]["state"], "start_outcome_unknown")
        self.assertFalse(result["pass"])
        for path in Path(result["run_dir"]).rglob("*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(secret, text)
            self.assertNotIn("private error body", text)

    def test_pack_hashes_verified_before_any_network_mutation(self):
        self.adapter.verify_pack.side_effect = ValueError("PRIVATE details")
        client = FakeClient(rows())
        with self.assertRaisesRegex(r.RunnerError, "pack_integrity_failed"):
            self.execute(client=client)
        self.assertEqual(client.requests, [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_pack_change_after_preflight_stops_before_first_post(self):
        self.adapter.verify_pack.side_effect = [None, ValueError("changed source")]
        result, _, client = self.execute()
        self.assertEqual(result["error_code"], "pack_integrity_failed")
        self.assertTrue(all(method == "GET" for method, _, _, _ in client.requests))

    def test_rebuilt_manifest_cannot_replace_initial_source_freeze(self):
        self.adapter.verify_pack.side_effect = [{"inputs": [{"sha256": "original"}]},
                                               {"inputs": [{"sha256": "changed"}]}]
        result, _, client = self.execute()
        self.assertEqual(result["error_code"], "pack_integrity_failed")
        self.assertTrue(all(method == "GET" for method, _, _, _ in client.requests))

    def test_secrets_in_json_system_events_redacted(self):
        payload = {"messages": [{"message": json.dumps({"headers": {"Authorization": "Bearer private"}, "token": "private-token", "text": "known-secret"})}]}
        text = json.dumps(r.scrub(payload, ("known-secret",)))
        self.assertNotIn("Bearer private", text)
        self.assertNotIn("private-token", text)
        self.assertNotIn("known-secret", text)

    def test_client_workspace_cache_bound_to_origin_and_request_budget(self):
        requests = []
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        def urlopen(request, timeout):
            requests.append((request.full_url, timeout))
            ws = "ws_first" if "first.invalid" in request.full_url else "ws_second"
            return Response(json.dumps({"data": {"result": {"workspaces": [{"id": ws}]}}}).encode())
        with patch.dict(os.environ, {"FREYA_API_URL": "https://first.invalid"}, clear=True), patch("urllib.request.urlopen", side_effect=urlopen):
            first = r.OfficialClient(b.KIT, r.Budget(2, self.clock.clock, self.clock.sleep))
            self.assertEqual(first.workspace_id(), "ws_first")
            os.environ["FREYA_API_URL"] = "https://second.invalid"
            second = r.OfficialClient(b.KIT, r.Budget(2, self.clock.clock, self.clock.sleep))
            self.assertEqual(second.workspace_id(), "ws_second")
            self.assertEqual(first.workspace_id(), "ws_first")
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(timeout <= 2 for _, timeout in requests))

    def test_plain_http_outage_retains_status_without_decoding_or_exposing_body(self):
        error=r.urllib.error.HTTPError('https://test.invalid',500,'internal',{},io.BytesIO(b'PRIVATE_BODY'))
        with patch.dict(os.environ,{'FREYA_BANK_TEAM_KEY':'UNIT_TEST_NAMESPACE'},clear=True),patch('urllib.request.urlopen',side_effect=error):
            client=r.OfficialClient(b.KIT,r.Budget(2,self.clock.clock,self.clock.sleep))
            with self.assertRaisesRegex(r.RunnerError,'^http_response_error_500$'):
                client.bank('/v1/practice/sessions',{'case':'PUB-01'})

    def test_isolated_original_client_recovers_get_503_with_same_budget(self):
        error = r.urllib.error.HTTPError('https://test.invalid', 503, 'unavailable', {}, io.BytesIO(b'PRIVATE_BODY'))
        response = io.BytesIO(b'{"customer_id":"opaque"}')
        with patch.dict(os.environ, {'FREYA_BANK_TEAM_KEY': 'UNIT_TEST_NAMESPACE'}, clear=True), \
                patch('urllib.request.urlopen', side_effect=[error, response]) as opener:
            client = r.OfficialClient(b.KIT, r.Budget(60, self.clock.clock, self.clock.sleep))
            self.assertEqual(client.bank('/v1/practice/ledger/opaque'), {'customer_id': 'opaque'})
        self.assertEqual(opener.call_count, 2)
        self.assertEqual(self.clock.waits, [10])
        self.assertEqual([args[0].get_method() for args, _ in opener.call_args_list], ['GET', 'GET'])

    def test_isolated_original_client_never_retries_unknown_post_503(self):
        error = r.urllib.error.HTTPError('https://test.invalid', 503, 'unavailable', {}, io.BytesIO(b'PRIVATE_BODY'))
        with patch.dict(os.environ, {'FREYA_BANK_TEAM_KEY': 'UNIT_TEST_NAMESPACE'}, clear=True), \
                patch('urllib.request.urlopen', side_effect=error) as opener:
            client = r.OfficialClient(b.KIT, r.Budget(60, self.clock.clock, self.clock.sleep))
            with self.assertRaisesRegex(r.RunnerError, '^http_response_error_503$'):
                client.bank('/v1/practice/sessions', {'case': 'PUB-01'})
        self.assertEqual(opener.call_count, 1)
        self.assertEqual(self.clock.waits, [])
        self.assertEqual(opener.call_args.args[0].get_method(), 'POST')


if __name__ == "__main__":
    unittest.main()
