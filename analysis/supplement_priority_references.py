from __future__ import annotations

import re
import shutil
from pathlib import Path


PAPER_DIR = Path(r"F:\IJDRR write\论文初稿模块")
TARGETS = [
    PAPER_DIR / "IJDRR_main_manuscript_v2_refs_resolved.md",
    PAPER_DIR / "IJDRR_full_paper_v2_refs_resolved.md",
]
BACKUP_SUFFIX = ".bak_20260704_priority_refs"


NEW_REFERENCES = {
    3: "R. Gonzalez-Pozo, Social profiles and response patterns during the 2025 Iberian Peninsula power outage: The case of Spain, International Journal of Disaster Risk Reduction 130 (2025) 105813. https://doi.org/10.1016/j.ijdrr.2025.105813.",
    4: "F. Mahdavian, Communication blackouts in power outages: Findings from scenario exercises in Germany and France, International Journal of Disaster Risk Reduction (2020).",
    5: "G. Raman, B. AlShebli, M. Waniek, T. Rahwan, J.C.-H. Peng, How weaponizing disinformation can bring down a city's power grid, PLOS ONE 15 (2020) e0236517. https://doi.org/10.1371/journal.pone.0236517.",
    9: "Y. Yang, H. Liu, S. Zhong, K. Liu, M. Wang, Q. Huang, Agent-based societal impact modeling for infrastructure disruption and countermeasures analyses, Sustainable Cities and Society 97 (2023) 104737. https://doi.org/10.1016/j.scs.2023.104737.",
    10: "B. Barnes, Improving human behaviour in macroscale city evacuation agent-based simulation, International Journal of Disaster Risk Reduction (2021).",
    11: "G. Bernardini, G. Romano, L. Soldini, E. Quagliarini, How urban layout and pedestrian evacuation behaviours can influence flood risk assessment in riverine historic built environments, Sustainable Cities and Society 70 (2021) 102876. https://doi.org/10.1016/j.scs.2021.102876.",
    12: "M. Shirvani, G. Kesserwani, Flood-pedestrian simulator for modelling human response dynamics during flood-induced evacuation: Hillsborough stadium case study, Natural Hazards and Earth System Sciences 21 (2021) 3175-3198. https://doi.org/10.5194/nhess-21-3175-2021.",
    13: "C. Flores, H.S. Lee, E. Mas, Understanding tsunami evacuation via a social force model while considering stress levels using agent-based modelling, Sustainability 16 (2024) 4307. https://doi.org/10.3390/su16104307.",
    14: "T. Takabatake, Influence of road blockage on tsunami evacuation: A comparative study of three different coastal cities in Japan, International Journal of Disaster Risk Reduction (2022).",
    15: "L. Zhuo, D. Han, Agent-based modelling and flood risk management: A compendious literature review, Journal of Hydrology 591 (2020) 125600. https://doi.org/10.1016/j.jhydrol.2020.125600.",
}


OLD_TO_NEW = {
    1: 1,
    2: 2,
    3: 6,
    4: 7,
    5: 8,
    6: 16,
    7: 17,
    8: 18,
    9: 19,
    10: 20,
    11: 21,
    12: 22,
    13: 23,
    14: 24,
    15: 25,
    16: 26,
    17: 27,
    18: 28,
    19: 29,
    20: 30,
    21: 31,
    22: 32,
    23: 33,
    24: 34,
    25: 35,
    26: 36,
    27: 37,
    28: 38,
    29: 39,
}


def parse_old_refs(ref_text: str) -> dict[int, str]:
    refs: dict[int, str] = {}
    current_num = None
    current_lines: list[str] = []
    for line in ref_text.splitlines():
        match = re.match(r"^\[(\d+)\]\s*(.*)$", line.strip())
        if match:
            if current_num is not None:
                refs[current_num] = " ".join(part.strip() for part in current_lines if part.strip())
            current_num = int(match.group(1))
            current_lines = [match.group(2)]
        elif current_num is not None and line.strip():
            current_lines.append(line.strip())
    if current_num is not None:
        refs[current_num] = " ".join(part.strip() for part in current_lines if part.strip())
    return refs


def split_body_refs(text: str) -> tuple[str, str, str]:
    if "# References" not in text:
        raise ValueError("No # References section found")
    body, tail = text.split("# References", 1)
    if "\n# Supplementary Material" in tail:
        refs_text, suffix = tail.split("\n# Supplementary Material", 1)
        return body, refs_text, "\n# Supplementary Material" + suffix
    return body, tail, ""


def compress_numbers(nums: list[int]) -> str:
    if not nums:
        return ""
    nums = sorted(dict.fromkeys(nums))
    parts: list[str] = []
    start = prev = nums[0]
    for num in nums[1:]:
        if num == prev + 1:
            prev = num
        else:
            parts.append(format_number_run(start, prev))
            start = prev = num
    parts.append(format_number_run(start, prev))
    return ",".join(parts)


def format_number_run(start: int, end: int) -> str:
    if end - start >= 2:
        return f"{start}-{end}"
    if start == end:
        return str(start)
    return f"{start},{end}"


def remap_citations(body: str) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        pieces = re.split(r"\s*,\s*", raw)
        mapped: list[int] = []
        for piece in pieces:
            if not piece:
                return match.group(0)
            if "-" in piece:
                left, right = piece.split("-", 1)
                if not (left.strip().isdigit() and right.strip().isdigit()):
                    return match.group(0)
                start, end = int(left), int(right)
                if start > end or not all(num in OLD_TO_NEW for num in range(start, end + 1)):
                    return match.group(0)
                mapped.extend(OLD_TO_NEW[num] for num in range(start, end + 1))
            else:
                if not piece.strip().isdigit():
                    return match.group(0)
                num = int(piece)
                if num not in OLD_TO_NEW:
                    return match.group(0)
                mapped.append(OLD_TO_NEW[num])
        return "[" + compress_numbers(mapped) + "]"

    return re.sub(r"\[([0-9][0-9,\-\s]*)\]", repl, body)


def insert_priority_context(body: str) -> str:
    if "The 2025 Iberian Peninsula outage survey" not in body:
        anchor = (
            "Disaster-risk-reduction (DRR) planning needs models that can represent this behavioural layer "
            "at the same spatial resolution as the road and shelter network on which emergency movement actually occurs [1,2]."
        )
        addition = (
            "\n\nRecent blackout-specific studies sharpen this point. The 2025 Iberian Peninsula outage survey shows that emotional vulnerability, "
            "preparedness and access to information differ across social groups [3], scenario exercises in Germany and France identify communication loss "
            "and expectations of government support as central behavioural issues in multi-day outages [4], and disinformation-driven demand shifts can "
            "amplify stress on the power grid itself [5]."
        )
        if anchor not in body:
            raise ValueError("Introduction blackout anchor not found")
        body = body.replace(anchor, anchor + addition, 1)

    if "Related outdoor-disaster evacuation ABMs demonstrate" not in body:
        anchor = (
            "If the road graph merely changes travel time, it is a transport detail. "
            "If it inserts a new action into the choice set, it is a behavioural intervention."
        )
        addition = (
            "\n\nRelated outdoor-disaster evacuation ABMs demonstrate that infrastructure disruption, urban layout, road blockage, floodwater dynamics and "
            "shelter or safe-zone conditions can strongly reshape realised evacuation patterns [9-15]. However, these models are typically developed for "
            "flood or tsunami hazards and do not make blackout-specific scarcity, information loss and shelter visibility compete inside one tactical choice set."
        )
        if anchor not in body:
            raise ValueError("Introduction outdoor-ABM anchor not found")
        body = body.replace(anchor, anchor + addition, 1)

    if "More recent blackout studies widen this view" not in body:
        anchor = (
            "Engineering research, by contrast, has extensively modelled the *technical* resilience and restoration "
            "of the grid and of interdependent critical infrastructure [2,29,30]."
        )
        addition = (
            " More recent blackout studies widen this view from infrastructure restoration to household preparedness, "
            "communication failure and information manipulation: survey evidence from Spain identifies heterogeneous social response profiles [3], "
            "scenario exercises in Germany and France foreground the behavioural consequences of communication loss [4], and city-scale demand manipulation "
            "shows how social information can itself become a grid-risk pathway [5]. Agent-based societal-impact modelling has also begun to couple households, "
            "stores, shelters and government countermeasures under infrastructure disruption [9]."
        )
        if anchor not in body:
            raise ValueError("Related-work blackout anchor not found")
        body = body.replace(anchor, anchor + addition, 1)

    if "Recent outdoor flood and tsunami evacuation studies point to the same limitation" not in body:
        anchor = (
            "This motivates our centrality-failure test: we compare standard node BC with observed road load and then use the mismatch "
            "to argue for demand-aware, shelter-aware centrality rather than topology-only proxies."
        )
        addition = (
            "\n\nRecent outdoor flood and tsunami evacuation studies point to the same limitation from the hazard side: realised evacuation outcomes change "
            "when models include urban form, road blockage, floodwater-pedestrian coupling, stress, safe-zone capacity and agent decision rules [10-15]. "
            "Their common lesson is that spatial topology must be interpreted through the demand, hazard and behavioural layers that activate particular corridors."
        )
        if anchor not in body:
            raise ValueError("Network-centrality anchor not found")
        body = body.replace(anchor, anchor + addition, 1)

    if "Even recent macroscale city and flood/tsunami evacuation ABMs" not in body:
        anchor = (
            "Crowd-dynamics studies typically validate on a single block or scenario, and panic-buying models are aspatial; consequently it is not known "
            "whether mechanism-level claims (e.g. road-network embedding activates shelter seeking and substitutes against herding; topology-based centrality "
            "predicts where pedestrians accumulate) hold across cities with different street-network geometries and shelter distributions."
        )
        replacement = (
            "Crowd-dynamics studies typically validate on a single block or scenario, and panic-buying models are aspatial. "
            "Even recent macroscale city and flood/tsunami evacuation ABMs tend to focus on one hazard class, one urban setting or one network intervention [10-15]. "
            "Consequently it is not known whether mechanism-level claims (e.g. road-network embedding activates shelter seeking and substitutes against herding; "
            "topology-based centrality predicts where pedestrians accumulate) hold across cities with different street-network geometries and shelter distributions."
        )
        if anchor not in body:
            raise ValueError("Generalisability anchor not found")
        body = body.replace(anchor, replacement, 1)

    return body


def build_reference_section(old_refs: dict[int, str]) -> str:
    new_refs: dict[int, str] = {}
    for old_num, new_num in OLD_TO_NEW.items():
        if old_num not in old_refs:
            raise ValueError(f"Old reference [{old_num}] not found")
        new_refs[new_num] = old_refs[old_num]
    new_refs.update(NEW_REFERENCES)

    lines = ["# References", ""]
    for num in range(1, 40):
        if num not in new_refs:
            raise ValueError(f"New reference [{num}] missing")
        lines.append(f"[{num}] {new_refs[num]}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def update_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if "Social profiles and response patterns during the 2025 Iberian Peninsula power outage" in text and "[39]" in text:
        return []

    body, refs_text, suffix = split_body_refs(text)
    old_refs = parse_old_refs(refs_text)
    body = remap_citations(body)
    body = insert_priority_context(body)
    references = build_reference_section(old_refs)
    new_text = body.rstrip() + "\n\n" + references + suffix

    backup = path.with_name(path.name + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(new_text, encoding="utf-8", newline="")
    return ["remapped citations", "inserted priority literature context", "rebuilt 39-item reference list"]


def main() -> int:
    for target in TARGETS:
        changes = update_file(target)
        if changes:
            print(f"{target.name}: " + "; ".join(changes))
        else:
            print(f"{target.name}: already updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
