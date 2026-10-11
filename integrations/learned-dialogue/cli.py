"""Local CLI; literal utterances must be fictional research inputs."""
import argparse
import json
from inference import local_snapshot, predict
from train_eval import load_model
from validation import validate_proposal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("utterance")
    args = parser.parse_args()
    snapshot = local_snapshot(args.utterance)
    proposal = predict(snapshot, load_model())
    validate_proposal(proposal, snapshot)
    print(json.dumps(proposal, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
