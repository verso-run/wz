"""A stand-in for a signal generator: a reproducible moisture trace (dry-down, watering, noise)."""
import argparse
import random

ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--n", type=int, default=600)
ap.add_argument("--out", required=True)
a = ap.parse_args()
rng = random.Random(a.seed)
level, lines = 450, ["# generated moisture trace, seed %d" % a.seed]
for i in range(a.n):
    level += -1 if level > 360 else 60
    lines.append(str(level + rng.randint(-4, 4)))
open(a.out, "w").write("\n".join(lines) + "\n")
