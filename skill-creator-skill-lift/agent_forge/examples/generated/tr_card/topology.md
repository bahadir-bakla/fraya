# Topology: ornek_banka_a_s_kart_hizmetleri_gelen_cagri_pros

```mermaid
flowchart LR
    caller((caller)) --> core
    core["core<br/><small>§2.1, §3.1, §5.1</small>"]
    block_card["block_card<br/><small>§4.1</small>"]
    core -->|"block_card + event:identity_verified"| block_card
```
