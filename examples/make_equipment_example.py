"""Write an explicitly synthetic dataset for an offline optimizer demonstration."""
import json
import time
from pathlib import Path


def stats(life,fire):
    return [{"metric":"flat_life","value":life},{"metric":"fire_resistance","value":fire}]


def main():
    now=int(time.time())
    payload={"schema_version":1,"origin":"synthetic_example","league":"Forbidden Rites","build_id":None,
        "current":[{"key":"old_left","slot":"ring_left","stats":stats(50,30)},
                   {"key":"old_right","slot":"ring_right","stats":stats(50,30)}],
        "candidates":[{"key":key,"eligible_slots":["ring_left","ring_right"],"stats":stats(life,fire),
            "price":{"amount":price,"currency":"exalted"},"observed_at_epoch":now}
            for key,life,fire,price in [("life_ring",120,0,10),("resist_ring",60,60,12),("balanced_ring",90,30,9)]]}
    path=Path("equipment-example.json")
    with path.open("x") as file:
        json.dump(payload,file,indent=2)
    print("Created equipment-example.json (synthetic; not actual gear or market quotes).")


if __name__=="__main__":
    main()
