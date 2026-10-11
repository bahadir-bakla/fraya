"""SGD TRAIN -> bounded observed-input JSONL minibatch shards; never fit a model.

Two streaming file passes: freeze dialogue/duplicate-input closure and splits,
then emit USER examples. Current/previous annotations are TARGETS only. Input
sanitation and duplicate grouping use only observed speaker/utterance strings.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import time
import unicodedata

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
CACHE = ROOT / ".cache"
LOCAL = REPO / "local-runs/customer-benchmark-day2-sgd"
REV = "e852981ae34990f4358979625854259302feaa78"
WINDOW = 8
MAX_SHARD = 19_500_000
SEED = "sgd-official-train-observed-input-closure-20261011-v1"
SPLITS = ("TRAIN", "CAL", "EVAL")
PUBLIC_USER_ACTS = ["INFORM_INTENT", "NEGATE_INTENT", "AFFIRM_INTENT", "INFORM", "REQUEST", "AFFIRM", "NEGATE", "SELECT", "REQUEST_ALTS", "THANK_YOU", "GOODBYE"]


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def line(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def rel(path):
    return Path(path).relative_to(REPO).as_posix()


TEXT_PATTERNS = [
    ("contact", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|\b(?:https?://|www\.)\S+", re.I)),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){10,30}\b", re.I)),
    ("address", re.compile(r"\b\d{1,6}\s+(?:[A-Z][\w'-]*\s+){1,6}(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr)\b", re.I)),
    ("declared_identity", re.compile(r"\b(?:my name is|i am named|i am called|my address is|i live at|my phone number is|my username is|my date of birth is|my birthday is|maiden name is)\s+[^.!?;\n]+", re.I)),
    ("secret", re.compile(r"\b(?:password|passcode|security answer|cvv|cvc|pin(?: number| code)?)\s*(?:is|was|:|=)\s+(?!(?:not|wrong|incorrect|invalid|blocked|locked|forgotten|missing|expired|unknown|working|needed|the|a|an)\b)[^.!?;\n]+", re.I)),
    ("spoken_number", re.compile(r"\b(?:(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)[ ,.-]+){3,}(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)\b", re.I)),
    ("number", re.compile(r"\d+(?:[ .,/:'-]\d+)*")),
]
CAPITAL = re.compile(r"\b[A-Z][a-z]+(?:[ -][A-Z][a-z]+)*\b")
COMMON = set("I Can Could Would Will What Where Which Who Why When How Please Thanks Thank Hello Hi Yes No Okay Ok Sure Good Great Fine My The A An This That These Those There Here It Its Is Are Was Were Do Does Did Have Has Had We You Your Our They Their He She Also And But Not Dont True False None Book Find Show Make Send Tell Check Get Give Search Reserve Let Im Ive Ill Id Its Thats Were Youre Ive Id January February March April May June July August September October November December Monday Tuesday Wednesday Thursday Friday Saturday Sunday".casefold().split())
NUMBER_WORDS = re.compile(r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million)\b", re.I)


def scrub(text):
    require(isinstance(text, str) and len(text) <= 20000, "Invalid utterance")
    result = unicodedata.normalize("NFKC", text)
    counts = Counter()
    for name, pattern in TEXT_PATTERNS:
        result, count = pattern.subn("[REDACTED]", result)
        counts[name] += count
    def proper(match):
        words = match.group().split()
        if all(w.casefold() in COMMON for w in words):
            return match.group()
        counts["possible_name"] += 1
        return "[REDACTED]"
    result = CAPITAL.sub(proper, result)
    result = " ".join(result.split())
    require(not any(c.isdigit() for c in result), "Residual numeric span")
    return result, Counter({k:v for k,v in counts.items() if v})


def normalize(text):
    value = unicodedata.normalize("NFKC", text).casefold().replace("\u2019", "'")
    for a,b in (("won't","will not"),("can't","can not"),("cannot","can not"),("n't"," not"),("'re"," are"),("'ve"," have"),("'ll"," will"),("i'm","i am"),("it's","it is"),("that's","that is"),("'d"," would")):
        value = value.replace(a,b)
    value = NUMBER_WORDS.sub("slotvalue", value)
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


def observed(dialogue):
    result, counts = [], Counter()
    for turn in dialogue["turns"]:
        require(turn["speaker"] in ("USER", "SYSTEM"), "Unknown source speaker")
        text, redactions = scrub(turn["utterance"])
        counts.update(redactions)
        result.append({"speaker": turn["speaker"], "text": text})
    return result, counts


def input_for(turns, index):
    require(turns[index]["speaker"] == "USER", "Only USER examples")
    return {"speaker": "USER", "utterance": turns[index]["text"],
            "earlier_context": turns[max(0,index-WINDOW):index]}


def feature_key(turns, index):
    # Exactly the declared observed input window. No frames, service IDs or gold
    # slot spans participate in the key or in inference features.
    return sha(line([(x["speaker"], normalize(x["text"])) for x in turns[max(0,index-WINDOW):index+1]]))


class Union:
    def __init__(self):
        self.parent = {}
    def add(self, ident):
        require(ident not in self.parent, "Duplicate source dialogue_id")
        self.parent[ident] = ident
    def root(self, ident):
        while self.parent[ident] != ident:
            self.parent[ident] = self.parent[self.parent[ident]]
            ident = self.parent[ident]
        return ident
    def join(self, a,b):
        a,b = self.root(a),self.root(b)
        self.parent[max(a,b)] = min(a,b)


def source_files(limit):
    inventory = json.loads((ROOT/"source-inventory.json").read_bytes())
    require(inventory["revision"] == REV and inventory["license"] == "CC-BY-SA-4.0", "Unexpected source/license")
    items = sorted((x for x in inventory["files"] if x["path"].startswith("train/dialogues_")),key=lambda x:x["path"])
    if limit:
        require(0 < limit < len(items), "Partial file count out of range")
        items = items[:limit]
    for item in items:
        path = CACHE/item["path"].replace("/","__")
        require(path.is_file() and path.stat().st_size == item["size"], "Collect pinned source first: "+item["path"])
    return items


def read_source(item):
    data = (CACHE/item["path"].replace("/","__")).read_bytes()
    blob = hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
    require(len(data)==item["size"] and blob==item["sha"], "Source ancestry mismatch")
    dialogs = json.loads(data)
    require(isinstance(dialogs,list) and dialogs, "Invalid source shard")
    return dialogs, sha(data)


def index_sources(items):
    union, duplicate_keys, meta = Union(), {}, {}
    counts, redactions = Counter(), Counter()
    source_pins, duplicate_hits = [], Counter()
    for number,item in enumerate(items,1):
        dialogs, digest = read_source(item)
        source_pins.append({"path":item["path"],"url":"https://raw.githubusercontent.com/google-research-datasets/dstc8-schema-guided-dialogue/"+REV+"/"+item["path"],"sha256":digest,"bytes":item["size"],"publisher_blob_sha1":item["sha"],"dialogues":len(dialogs)})
        for dialog in dialogs:
            ident=dialog["dialogue_id"]
            union.add(ident)
            turns, changes = observed(dialog)
            redactions.update(changes)
            user_count=sum(x["speaker"]=="USER" for x in turns)
            meta[ident]={"source_file":item["path"],"turns":len(turns),"user_turns":user_count}
            counts.update(dialogues=1,turns=len(turns),USER_turns=user_count,SYSTEM_turns=len(turns)-user_count)
            keys=[("whole_dialogue",sha(line([(t["speaker"],normalize(t["text"])) for t in turns])))]
            keys.extend(("observed_input",feature_key(turns,i)) for i,t in enumerate(turns) if t["speaker"]=="USER")
            for kind,key in keys:
                marker=kind+":"+key
                if marker in duplicate_keys:
                    union.join(ident,duplicate_keys[marker])
                    duplicate_hits[kind]+=1
                else:
                    duplicate_keys[marker]=ident
        if number%10==0 or number==len(items):
            print(json.dumps({"stage":"index","source_files":number,"dialogues":counts["dialogues"],"USER_turns":counts["USER_turns"]}),flush=True)
    components=defaultdict(list)
    for ident in meta:
        components[union.root(ident)].append(ident)
    groups={root:"sgd:"+sha(line(sorted(members))) for root,members in components.items()}
    ordered=sorted(components,key=lambda root:(-len(components[root]),sha((SEED+groups[root]).encode())))
    total=len(meta)
    assignments, allocated={},Counter()
    if len(ordered)<3:
        assignments={root:"TRAIN" for root in ordered}
    else:
        # Reserve the smallest two real closure components for heldout splits.
        assignments[ordered[-1]]="EVAL";allocated["EVAL"]+=len(components[ordered[-1]])
        assignments[ordered[-2]]="CAL";allocated["CAL"]+=len(components[ordered[-2]])
        desired={"TRAIN":total*.8,"CAL":total*.1,"EVAL":total*.1}
        for root in ordered[:-2]:
            split=max(SPLITS,key=lambda s:(desired[s]-allocated[s],-SPLITS.index(s)))
            assignments[root]=split;allocated[split]+=len(components[root])
    for ident,entry in meta.items():
        root=union.root(ident)
        entry.update(group_id=groups[root],split=assignments[root])
    summary={"source_counts":dict(counts),"source_redaction_spans":dict(redactions),"closure_components":len(components),"largest_component_dialogues":max(map(len,components.values())),"component_size_histogram":dict(Counter(map(len,components.values()))),"duplicate_feature_hits":dict(duplicate_hits),"split_dialogues":dict(Counter(x["split"] for x in meta.values())),"split_USER_examples":dict(Counter({s:sum(x["user_turns"] for x in meta.values() if x["split"]==s) for s in SPLITS}))}
    return meta,summary,source_pins


def value_targets(values, visible):
    require(isinstance(values,list) and all(isinstance(v,str) for v in values), "Invalid slot/action values")
    result=[]
    for value in values:
        cleaned,_=scrub(value)
        recoverable=bool(value.strip()) and cleaned==" ".join(unicodedata.normalize("NFKC",value).split()) and value.casefold() in visible.casefold()
        result.append({"text":cleaned if recoverable else None,"value_recoverability_mask":recoverable,"source_value_sha256":sha(value.encode())})
    return result


def frame_targets(frame, schemas, previous, visible, stats):
    service=frame["service"]
    require(service in schemas,"Service not in official TRAIN schema")
    schema=schemas[service];slot_names=[x["name"] for x in schema["slots"]]
    intent_names=["NONE"]+[x["name"] for x in schema["intents"]]
    state=frame.get("state")
    state_known=isinstance(state,dict)
    active_known=state_known and "active_intent" in state
    requested_known=state_known and isinstance(state.get("requested_slots"),list)
    values_known=state_known and isinstance(state.get("slot_values"),dict)
    active=state.get("active_intent") if active_known else None
    require(not active_known or active in intent_names,"Unknown publisher active_intent")
    requested=state["requested_slots"] if requested_known else []
    values=state["slot_values"] if values_known else {}
    require(set(requested)<=set(slot_names) and set(values)<=set(slot_names),"Unknown state slot")
    value_rows={name:value_targets(vals,visible) for name,vals in values.items()}
    prior_known=isinstance(previous,dict) and isinstance(previous.get("slot_values"),dict)
    prior_values=previous["slot_values"] if prior_known else {}
    updates=[]
    for name in slot_names:
        update, known, reason="UNKNOWN",False,"current_or_consecutive_previous_state_unknown"
        if values_known and prior_known:
            if name in values:
                update="KEEP" if name in prior_values and set(values[name])==set(prior_values[name]) else "SET"
                now_safe=bool(value_rows[name]) and all(x["value_recoverability_mask"] for x in value_rows[name])
                old_safe=name not in prior_values or all(x["value_recoverability_mask"] for x in value_targets(prior_values[name],visible))
                known=now_safe and old_safe
                reason="published_consecutive_map_delta" if known else "value_identity_not_recoverable_after_text_only_scrub"
            elif name in prior_values:
                reason="removed_from_published_map_but_no_independent_completeness_certificate_for_DELETE"
            else:
                reason="absent_in_both_maps_no_value_update_target"
        updates.append({"slot_id":slot_names.index(name),"publisher_map_update":update,"update_mask":known,"reason":reason})
        stats["belief_update_"+(update if known else "masked")]+=1
    acts_known=isinstance(frame.get("actions"),list)
    actions=[]
    for action in frame.get("actions",[]) if acts_known else []:
        require(action["act"] in PUBLIC_USER_ACTS,"Unrecognized published USER act")
        slot=action.get("slot")
        actions.append({"act":action["act"],"slot":slot,"slot_schema_mask":slot in slot_names,"values":value_targets(action.get("values",[]),visible),"canonical_value_target_mask":False})
        stats["user_act:"+action["act"]]+=1
    stats.update(publisher_frames=1,state_known=int(state_known),active_intent_known=int(active_known),requested_slots_known=int(requested_known),slot_map_known=int(values_known),actions_known=int(acts_known))
    stats["value_targets"]+=sum(len(v) for v in value_rows.values())
    stats["value_recoverable_targets"]+=sum(x["value_recoverability_mask"] for v in value_rows.values() for x in v)
    stats["service_frames:"+service]+=1
    if active_known:stats["active_intent:"+service+"::"+active]+=1
    return {"service":service,"namespace":"sgd::"+service,"active_intent":active,"active_intent_id":intent_names.index(active) if active_known else None,
            "requested_slots":[int(x in requested) for x in slot_names] if requested_known else None,
            "published_slot_map_presence":[int(x in values) for x in slot_names] if values_known else None,
            "slot_values":value_rows,"belief_updates":updates,"actions":actions,
            "head_masks":{"active_intent":active_known,"requested_slots":requested_known,"published_slot_map_presence":values_known,"publisher_actions":acts_known,"bank_policy":False,"bank_permission":False,"ledger":False},
            "DELETE_mask":False,"absence_semantics":"membership in publisher state dictionary only; missing frame/state is UNKNOWN"}


class Shards:
    def __init__(self,directory):
        self.directory=directory;directory.mkdir(parents=True,exist_ok=True)
        self.opened={};self.outputs=[];self.serial=Counter()
    def close(self,split):
        if split not in self.opened:return
        handle,digest,count,size,path=self.opened.pop(split)
        handle.close();self.outputs.append({"path":rel(path),"split":split,"sha256":digest.hexdigest(),"bytes":size,"rows":count})
    def add(self,split,row):
        data=line(row);require(len(data)<=MAX_SHARD,"One example exceeds shard limit")
        if split in self.opened and self.opened[split][3]+len(data)>MAX_SHARD:self.close(split)
        if split not in self.opened:
            self.serial[split]+=1
            path=self.directory/(split.lower()+"-"+str(self.serial[split]).zfill(5)+".jsonl")
            self.opened[split]=[path.open("wb"),hashlib.sha256(),0,0,path]
        entry=self.opened[split];entry[0].write(data);entry[1].update(data);entry[2]+=1;entry[3]+=len(data)
    def finish(self):
        for split in list(self.opened):self.close(split)
        return sorted(self.outputs,key=lambda x:x["path"])


def emit(items,plan,schemas,directory):
    writer=Shards(directory)
    stats,redactions=Counter(),Counter()
    for number,item in enumerate(items,1):
        dialogs,_=read_source(item)
        for dialog in dialogs:
            ident=dialog["dialogue_id"];meta=plan[ident]
            clean,_=observed(dialog)
            previous_user_frames={}
            for index,turn in enumerate(dialog["turns"]):
                if turn["speaker"]!="USER":continue
                inputs=input_for(clean,index)
                visible="\n".join(x["text"] for x in inputs["earlier_context"])+"\n"+inputs["utterance"]
                frames=turn.get("frames")
                require(isinstance(frames,list),"Missing/invalid publisher frames list")
                targets=[frame_targets(f,schemas,previous_user_frames.get(f["service"]),visible,stats) for f in frames]
                require(len({f["service"] for f in frames})==len(frames),"Duplicate service frames")
                row={"schema_version":"sgd.observed-user-input.publisher-targets.v1","record_id":"sgd:"+ident+":"+str(index),
                     "input":inputs,"targets":{"frames":targets},"service_supervision_masks":{s:any(f["service"]==s for f in frames) for s in schemas},
                     "ancestry":{"dialogue_id":ident,"source_turn_index":index,"source_file":item["path"],"source_revision":REV,"group_id":meta["group_id"],"split":meta["split"]},
                     "bank_policy_target_mask":False,"ledger_target_mask":False}
                writer.add(meta["split"],row)
                stats["examples"]+=1;stats["examples:"+meta["split"]]+=1
                # Only consecutive USER frames qualify as prior state TARGETS.
                # This state is never appended to input or to schema features.
                previous_user_frames={f["service"]:f.get("state") for f in frames}
        if number%10==0 or number==len(items):print(json.dumps({"stage":"emit","source_files":number,"USER_examples":stats["examples"]}),flush=True)
    return writer.finish(),dict(stats)


def verify_shards(outputs,plan,expected):
    counts=Counter();ids=set();template_splits={};group_owners={};missing_states=0
    for spec in outputs:
        path=REPO/spec["path"];digest=hashlib.sha256();size=rows=0
        with path.open("rb") as handle:
            for data in handle:
                digest.update(data);size+=len(data);rows+=1
                row=json.loads(data);ancestry=row["ancestry"];split=ancestry["split"];ident=ancestry["dialogue_id"]
                require(row["record_id"] not in ids,"Duplicate emitted record");ids.add(row["record_id"])
                require(plan[ident]["group_id"]==ancestry["group_id"] and plan[ident]["split"]==split==spec["split"],"Broken ancestry/split closure")
                require(set(row["input"])=={"speaker","utterance","earlier_context"},"Gold/bookkeeping leaked into input")
                require(all(set(t)=={"speaker","text"} for t in row["input"]["earlier_context"]),"Gold leaked into context")
                texts=[row["input"]["utterance"]]+[t["text"] for t in row["input"]["earlier_context"]]
                require(len(row["input"]["earlier_context"])<=WINDOW and all(not any(c.isdigit() for c in t) and scrub(t)[0]==t for t in texts),"Input privacy/idempotence invariant")
                key=sha(line([(t["speaker"],normalize(t["text"])) for t in row["input"]["earlier_context"]]+[("USER",normalize(row["input"]["utterance"]))]))
                require(key not in template_splits or template_splits[key]==split,"Duplicate observed-input template across partitions")
                template_splits[key]=split
                root=ancestry["group_id"];require(root not in group_owners or group_owners[root]==split,"Closure group overlap");group_owners[root]=split
                require(not row["bank_policy_target_mask"] and not row["ledger_target_mask"],"Invented bank gold")
                for f in row["targets"]["frames"]:
                    require(not any(f["head_masks"][h] for h in ("bank_policy","bank_permission","ledger")) and not f["DELETE_mask"],"Unsafe target authority/delete")
                    if not f["head_masks"]["active_intent"]:require(f["active_intent"] is None,"Unknown state imputed")
                    for values in f["slot_values"].values():
                        for value in values:require(value["value_recoverability_mask"]==(value["text"] is not None),"Invalid value mask")
                counts[split]+=1
        require(size==spec["bytes"]<=MAX_SHARD and rows==spec["rows"] and digest.hexdigest()==spec["sha256"],"Shard hash/size/count mismatch")
    require(sum(counts.values())==expected and counts==Counter({s:sum(x["rows"] for x in outputs if x["split"]==s) for s in SPLITS}),"Total accounting mismatch")
    return {"status":"passed","shard_rows":dict(counts),"duplicate_record_ids":0,"cross_partition_dialogue_or_closure_overlap":0,"cross_partition_exact_or_delexicalized_observed_input_overlap":0,"current_gold_in_input_fields":0,"unknown_state_imputation":0,"invented_DELETE_targets":0,"bank_policy_permission_ledger_gold":0,"all_shards_max_bytes":MAX_SHARD}


def self_test():
    raw={"turns":[{"speaker":"SYSTEM","utterance":"Can I help?","frames":[{"secret":"old"}]},{"speaker":"USER","utterance":"My phone number is 1234567890.","frames":[{"state":{"active_intent":"gold"}}]}]}
    a=observed(raw)[0]
    raw["turns"][0]["frames"]=[{"secret":"mutated"}];raw["turns"][1]["frames"]=[{"state":{"active_intent":"different_gold"}}]
    require(a==observed(raw)[0],"Annotation mutation changed input")
    require(scrub(scrub("My password is huntertwo. Send money to Alice Smith.")[0])[0]==scrub("My password is huntertwo. Send money to Alice Smith.")[0],"Privacy not idempotent")
    schema={"S":{"slots":[{"name":"x"}],"intents":[{"name":"I"}]}}
    missing=frame_targets({"service":"S","actions":[]},schema,{"slot_values":{"x":["safe"]}},"safe",Counter())
    require(not missing["head_masks"]["active_intent"] and missing["active_intent"] is None and not missing["belief_updates"][0]["update_mask"],"Missing state treated as negative/delete")
    return {"status":"passed","checks":["all annotation mutations leave input unchanged","text-only privacy idempotence","missing state remains unknown","no DELETE inference"]}


def build(limit):
    require(self_test()["status"]=="passed","Regression failure")
    items=source_files(limit);version="partial-"+str(limit).zfill(4) if limit else "full-v1"
    destination=ROOT/version;destination.mkdir(exist_ok=True)
    local=LOCAL/version
    schemas_list=json.loads((ROOT/"service-schema.json").read_bytes());schemas={s["service_name"]:s for s in schemas_list}
    require(len(schemas)==26,"Unexpected TRAIN service schema")
    started=time.monotonic()
    plan,index_counts,pins=index_sources(items)
    plan_bytes=encode({"seed":SEED,"algorithm":"union all whole-dialogue templates AND identical normalized observed-input windows; deterministic conversation-count deficit assignment, smallest two real components reserved for CAL/EVAL","dialogues":plan,"summary":index_counts})
    (destination/"split-plan.json").write_bytes(plan_bytes)
    outputs,target_counts=emit(items,plan,schemas,local)
    validation=verify_shards(outputs,plan,index_counts["source_counts"]["USER_turns"])
    validation["self_tests"]=self_test()
    status="partial_preview_not_fit_ready_global_closure_pending" if limit else "ready_for_streaming_publisher_head_minibatch_training" if index_counts["closure_components"]>=3 else "ready_TRAIN_only_insufficient_closure_components_for_holdouts"
    manifest={"schema_version":"sgd.training-packet.v1","status":status,"source":{"repo":"google-research-datasets/dstc8-schema-guided-dialogue","revision":REV,"official_split":"train","official_dev_test":"not_downloaded_or_used","license":"CC-BY-SA-4.0"},
              "source_files":pins,"counts":index_counts,"target_counts":target_counts,"outputs":outputs,"validation":validation,
              "source_inventory":{"path":rel(ROOT/"source-inventory.json"),"sha256":sha((ROOT/"source-inventory.json").read_bytes())},
              "processor":{"path":rel(Path(__file__).resolve()),"sha256":sha(Path(__file__).read_bytes())},"collector":{"path":rel(ROOT/"collect.py"),"sha256":sha((ROOT/"collect.py").read_bytes())},
              "split_plan":{"path":rel(destination/"split-plan.json"),"sha256":sha(plan_bytes)},
              "service_schema":{"path":rel(ROOT/"service-schema.json"),"sha256":sha((ROOT/"service-schema.json").read_bytes()),"services":26,"intent_heads":26,"namespaced_intents_excluding_NONE":53,"namespaced_slots":215},
              "feature_protocol":{"input_fields":["input.speaker","input.utterance","input.earlier_context[].speaker,text"],"context_earlier_turns":WINDOW,"current_frames_or_state_features":False,"prior_gold_state_features":False,"schema_descriptions":"All official TRAIN service schemas made available separately to every example; never select schemas using current gold frames. Current frame service is a target/supervision mask only.","schema_is_transactional":"publisher metadata only; no bank authority","privacy":"deterministic text-only regex and capitalized-name heuristic; no annotation-span markers. Values masked if not unchanged and visible in sanitized observed window.","graph":"Only observed turn order/speaker; all-service schema branch is a separately declared protocol. No current-gold frame edges."},
              "target_protocol":{"active_intent":"namespaced service-local CE; published NONE retained","requested_slots":"service-local schema order BCE only when requested_slots field exists","slot_presence":"publisher state dictionary membership only; mask requires slot_values dictionary","actions":"actual published USER action types and arguments; canonical values not exposed","belief_updates":"Consecutive USER frames for same service only; observed KEEP/SET map deltas supervise only if value identity recoverable. DELETE always unknown/masked: no independent annotation completeness certificate.","missing_state":"unknown, never negative/deleted","policy_permission_ledger":"untrained/unknown"},
              "ancestry_limits":{"internal_holdouts":"Derived from official TRAIN; not official dev/test and not blind policy OOD","independence":"Closure components are embargo units, not proven IID. Large connected components are reported, not split.","partial_full":"Partial preview and full packet share source ancestry; never claim them independent. Partial fitting before full closure freeze would contaminate future full holdouts.","pretrained_contamination":"Not audited; no pretrained model opened here"},
              "license_files":{name:{"path":rel(ROOT/name),"sha256":sha((ROOT/name).read_bytes())} for name in ("LICENSE.txt","PUBLISHER-README.md","NOTICE.txt","design-contract.json")},"models_trained":0}
    (destination/"manifest.json").write_bytes(encode(manifest));(destination/"validation.json").write_bytes(encode(validation))
    handoff={"status":status,"manifest":{"path":rel(destination/"manifest.json"),"sha256":sha(encode(manifest))},"split_shards":{s:[x for x in outputs if x["split"]==s] for s in SPLITS},"actual_counts":index_counts,"source_target_counts":target_counts,"train_iterator":"python research/customer-benchmark/day2-training-data/sgd/batches.py --manifest "+rel(destination/"manifest.json")+" --split TRAIN --batch-size 128","raw_cache":"ignored research/customer-benchmark/day2-training-data/sgd/.cache/","processed_local":"ignored local-runs/customer-benchmark-day2-sgd/","license":"CC-BY-SA-4.0 compatible distribution; preserve license and attribution","fit_authority":"Parent/Hooke authorize actual fit separately; this job collected/processed only"}
    (destination/"ready-handoff.json").write_bytes(encode(handoff))
    print(json.dumps({"status":status,"manifest":handoff["manifest"],"counts":index_counts,"processing_seconds":round(time.monotonic()-started,3)},sort_keys=True),flush=True)
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--limit-source-files",type=int);p.add_argument("--self-test",action="store_true");args=p.parse_args()
    if args.self_test:print(json.dumps(self_test()));return
    build(args.limit_source_files)


if __name__=="__main__":main()
