"""
Wie verrauscht ist das Blockmittel von beta?

Die Stop-Regel verlangt zwei aufeinanderfolgende relative Aenderungen des
Blockmittels <= 10 %. Ob das ueberhaupt erreichbar ist, haengt allein an der
Streuung von beta je Retrieval und an der Blockgroesse:

    sd(Blockmittel)      = sd(beta) / sqrt(B)
    sd(rel. Aenderung)  ~= sqrt(2) * sd(beta) / (sqrt(B) * mean(beta))

Daraus folgt die Blockgroesse, ab der eine Aenderung <= 10 % das Signal und
nicht das Rauschen misst.
"""
import json
import math
import statistics as st
import sys
from pathlib import Path

out_dir = Path(sys.argv[1])
alle = []

print(f"{'Policy':24s} {'seed':>4s} {'n':>4s} {'mean':>6s} {'sd':>6s} "
      f"{'cv':>6s} {'B fuer 10%':>10s}")
for f in sorted(out_dir.glob("*.json")):
    if f.name.endswith(".logcount.json"):
        continue
    d = json.loads(f.read_text())
    beta = [r["blocking_bins"] for r in d["retrievals"]
            if r["blocking_bins"] is not None]
    if len(beta) < 20:
        continue
    alle.extend(beta)
    m, s = st.mean(beta), st.pstdev(beta)
    cv = s / m if m else float("inf")
    # sqrt(2)*cv/sqrt(B) <= 0.10  ->  B >= 200 * cv^2
    b_needed = math.ceil(200 * cv * cv)
    print(f"{d['policy']:24s} {d['seed']:>4d} {len(beta):>4d} {m:>6.2f} "
          f"{s:>6.2f} {cv:>6.2f} {b_needed:>10d}")

m, s = st.mean(alle), st.pstdev(alle)
cv = s / m
print(f"\n{'GEPOOLT':24s} {'':>4s} {len(alle):>4d} {m:>6.2f} {s:>6.2f} "
      f"{cv:>6.2f} {math.ceil(200 * cv * cv):>10d}")
print(f"\nErwartete rel. Aenderung bei Blockgroesse 50 : "
      f"{math.sqrt(2) * cv / math.sqrt(50):.3f}")
for b in (100, 150, 200, 300, 400):
    print(f"Erwartete rel. Aenderung bei Blockgroesse {b:3d}: "
          f"{math.sqrt(2) * cv / math.sqrt(b):.3f}")
