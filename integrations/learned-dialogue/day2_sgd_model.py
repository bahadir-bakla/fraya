"""Small shared-query causal model. Zero-edge arm retains every direct path."""
import math
import torch
from torch import nn
from torch.nn import functional as F

HEADS = ("intent", "requested", "presence", "acts")


class SharedQueryGNN(nn.Module):
    def __init__(self, spec, query_features, relations=True):
        super().__init__()
        self.spec, self.relations = spec, relations
        self.register_buffer("query_features", torch.tensor(query_features, dtype=torch.float32), persistent=False)
        for name, shape in [("E", (512, 32)), ("node_bias", (32,)), ("query_bias", (32,)), ("Bcurrent", (32, 32)), ("Bcontext", (32, 32)), ("Bprior", (5, 32)), ("Wmessage", (2, 32, 32)), ("Bmessage", (32, 32)), ("Whead", (5, 32, 32)), ("head_bias", (5,)), ("prior_head", (5, 2))]:
            self.register_parameter(name, nn.Parameter(torch.randn(shape) * .05 if len(shape) > 1 else torch.zeros(shape)))

    def initial_memory(self, batch):
        return {"intent": torch.zeros(batch, self.spec["intent_count"]), "requested": torch.zeros(batch, self.spec["slot_count"]), "presence": torch.zeros(batch, self.spec["slot_count"]), "acts": torch.zeros(batch, self.spec["act_count"]), "known": torch.zeros(batch, 1)}

    def forward(self, x, node_mask, roles, prior):
        hidden = torch.tanh(x @ self.E + self.node_bias) * node_mask[..., None]
        count = node_mask.sum(1).clamp(min=1)
        current = hidden[torch.arange(len(x)), (count.long() - 1)]
        mean = hidden.sum(1) / count[:, None]
        entropy = -(prior["intent"] * torch.log(prior["intent"].clamp(min=1e-9))).sum(1) / len(self.spec["services"])
        summary = torch.stack((entropy, prior["requested"].mean(1), prior["presence"].mean(1), prior["acts"].mean(1), prior["known"][:, 0]), 1)
        base = current @ self.Bcurrent + mean @ self.Bcontext + summary @ self.Bprior
        if self.relations:
            earlier = hidden[:, :-1]
            message = torch.zeros_like(earlier)
            for role in (0, 1):
                message = message + (earlier @ self.Wmessage[role]) * (roles[:, :-1] == role)[..., None]
            edge_mask = node_mask[:, 1:] * node_mask[:, :-1]
            relation = (message * edge_mask[..., None]).sum(1) / edge_mask.sum(1).clamp(min=1)[:, None]
            base = base + relation @ self.Bmessage
        pooled = torch.tanh(base)
        queries = torch.tanh(self.query_features @ self.E + self.query_bias)
        logits = {}
        for hi, h in enumerate(HEADS):
            kind = "intent" if h == "intent" else "act" if h == "acts" else "slot"
            start, end = self.spec["query_slices"][kind]
            owner = self.spec["query_owners"][kind]
            q = (queries[start:end] + queries[owner]) / math.sqrt(2)
            previous = prior["presence"] if h == "updates" else prior[h]
            logits[h] = (pooled @ self.Whead[hi]) @ q.T / math.sqrt(32) + self.head_bias[hi] + previous * self.prior_head[hi, 0] + prior["known"] * self.prior_head[hi, 1]
        return logits

    def memory(self, logits):
        intents = []
        for service in self.spec["services"]:
            a = service["intent_offset"]
            intents.append(logits["intent"][:, a:a + len(service["intents"])].softmax(1))
        return {"intent": torch.cat(intents, 1).detach(), "requested": torch.zeros_like(logits["requested"]), "presence": logits["presence"].sigmoid().detach(), "acts": torch.zeros_like(logits["acts"]), "known": torch.ones(len(logits["intent"]), 1)}

    def masked_loss(self, logits, y, masks, weights):
        per_row = {}
        terms = []
        for sid, service in enumerate(self.spec["services"]):
            a, classes = service["intent_offset"], len(service["intents"])
            terms.append(F.cross_entropy(logits["intent"][:, a:a + classes], y["intent"][:, sid].long(), reduction="none") / math.log(max(2, classes)))
        values = torch.stack(terms, 1)
        per_row["intent"] = (values * masks["intent"]).sum(1) / masks["intent"].sum(1).clamp(min=1)
        for h in HEADS[1:]:
            values = F.binary_cross_entropy_with_logits(logits[h], y[h].float(), reduction="none") / math.log(2)
            per_row[h] = (values * masks[h]).sum(1) / masks[h].sum(1).clamp(min=1)
        multipliers = {"intent": 1, "requested": 1, "presence": 1, "acts": .5, "updates": .25}
        # Fixed 32*4 denominator preserves the declared per-event group mass
        # even for padded/end-dialogue positions. Loss terms have their own masks.
        total = sum((per_row[h] * weights).sum() * multipliers[h] / 128 for h in HEADS)
        return total, {h: float((per_row[h].detach() * weights).sum()) for h in HEADS}
