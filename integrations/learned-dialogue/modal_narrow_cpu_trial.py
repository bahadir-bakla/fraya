"""Parent's bounded CPU-first measurement; default only inspects local readiness.

No preparation step downloads weights. --parent-measure requires an admitted
TRAIN payload; it is intentionally never executed by this implementation task.
"""
import argparse
import importlib.metadata
import json
import subprocess
import sys
import time
from pathlib import Path

from modal_narrow_core import digest, load, validate_payload


def cost_decision(result, cpu_wall_seconds=300):
    elapsed = result.get("elapsed_seconds")
    complete = result.get("training_rows",0) > 0 and result.get("encoder_frozen") is True
    feasible = complete and type(elapsed) in (int,float) and 0 < elapsed <= cpu_wall_seconds
    return {"measured_cpu_feasible":feasible,"preferred_route":"CPU; skip GPU" if feasible else "NO-GO until reviewed GPU benefit and parent gates",
            "gpu_launch_authorized":False,"cost_benefit_basis":"Frozen representations reusable; tiny binary head adds little GPU work. CPU fit under 300s avoids cloud startup/build/download overhead.",
            "semantic_quality_established":False}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--parent-measure",action="store_true")
    parser.add_argument("--child",action="store_true",help=argparse.SUPPRESS)
    parser.add_argument("--payload")
    parser.add_argument("--model",default=str(Path(__file__).with_name("modal_narrow_model.json")))
    parser.add_argument("--cache",required=True)
    parser.add_argument("--result")
    args=parser.parse_args()
    if args.child:
        from modal_narrow_teacher import run_teacher
        blob=Path(args.payload).read_bytes()
        validate_payload(blob)
        result=run_teacher(blob,digest(blob),load(Path(args.model).read_bytes()),args.cache,290,time.time()+290,device="cpu",download=False)
        with Path(args.result).open("xb") as handle: handle.write(result)
    elif args.parent_measure:
        validate_payload(Path(args.payload).read_bytes())
        if Path(args.result).exists(): raise ValueError("CPU report must be a new path")
        command=[sys.executable,"-B",str(Path(__file__).resolve()),"--child","--payload",args.payload,"--model",args.model,"--cache",args.cache,"--result",args.result]
        try:
            completed=subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=300)
            result=load(Path(args.result).read_bytes()) if completed.returncode==0 else {}
            print(json.dumps(cost_decision(result),indent=2))
        except subprocess.TimeoutExpired:
            print(json.dumps({"measured_cpu_feasible":False,"bounded_cpu_timeout":True,"gpu_launch_authorized":False}))
    else:
        print(json.dumps({"pinned_weights_present":Path(args.cache,"model.safetensors").exists(),"weights_downloaded":False,
                          "cpu_inference_measured":False,"training_started":False,"gpu_launch_authorized":False,
                          "local_torch":importlib.metadata.version("torch"),"local_transformers":importlib.metadata.version("transformers")},indent=2))


if __name__ == "__main__": main()
