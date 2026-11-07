"""Creates FICTIONAL reference data in ./data (part master, supplier prices, margin rules).
Replace these CSVs with real company data when you have it - the code only needs the same columns."""
import csv
import random
from pathlib import Path

PARTS = [  # part_number, description, category, base unit cost (EUR)  - illustrative only
    ("BKR6E-11", "Spark plug nickel", "Spark plug", 1.05), ("BKR5E-11", "Spark plug nickel", "Spark plug", 0.95),
    ("BKR7E", "Spark plug nickel", "Spark plug", 1.00), ("ILKAR7B11", "Spark plug iridium", "Spark plug", 3.90),
    ("ILZKR7B11", "Spark plug iridium", "Spark plug", 4.30), ("ZFR6F-11", "Spark plug standard", "Spark plug", 1.10),
    ("ZSE-118", "Ignition coil", "Ignition coil", 14.50), ("ZSE-210", "Ignition coil pencil", "Ignition coil", 17.80),
    ("U5010", "Ignition coil pack", "Ignition coil", 21.00), ("Y-1001AS", "Glow plug", "Glow plug", 2.60),
    ("Y-1002AS", "Glow plug", "Glow plug", 2.95), ("NTK-LZA09", "Lambda sensor", "Lambda sensor", 26.00),
    ("NTK-OZA-684", "Oxygen sensor", "Lambda sensor", 31.50), ("NTK-MAF22", "MAF sensor", "MAF sensor", 36.00),
    ("NTK-MAP08", "MAP sensor", "MAP sensor", 18.50), ("NTK-NOX41", "NOx sensor", "NOx sensor", 118.00),
    ("NTK-EGR12", "EGR valve", "EGR valve", 64.00), ("NTK-CPS05", "Crankshaft position sensor", "Position sensor", 12.80),
]
SUPPLIERS = [  # name, cost factor, lead time days, MOQ, reliability  (all fictional)
    ("Kanto Components Ltd", 0.92, 35, 200, 0.93), ("Rhein Ignition GmbH", 1.05, 7, 50, 0.97),
    ("Silesia Parts Sp. z o.o.", 0.97, 14, 200, 0.90), ("Iberia Auto Supply S.L.", 1.00, 10, 100, 0.88),
]
MARGINS = {"Spark plug": 0.18, "Ignition coil": 0.22, "Glow plug": 0.20, "Lambda sensor": 0.24,
           "MAF sensor": 0.24, "MAP sensor": 0.24, "NOx sensor": 0.26, "EGR valve": 0.22, "Position sensor": 0.22}


def write(out="data"):
    out = Path(out)
    out.mkdir(exist_ok=True)
    rnd = random.Random(7)
    with open(out / "part_master.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["part_number", "description", "category"])
        w.writerows([p[:3] for p in PARTS])
    with open(out / "supplier_prices.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["part_number", "supplier", "unit_cost", "lead_time_days", "moq", "reliability"])
        for pn, _, _, base in PARTS:
            chosen = rnd.sample(SUPPLIERS, rnd.choice([2, 3, 4]))
            for name, factor, lead, moq, rel in chosen:
                w.writerow([pn, name, round(base * factor * rnd.uniform(0.97, 1.04), 2), lead, moq, rel])
    with open(out / "margin_rules.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "target_margin"])
        w.writerows(MARGINS.items())


if __name__ == "__main__":
    write()
    print("Reference data written to ./data")
