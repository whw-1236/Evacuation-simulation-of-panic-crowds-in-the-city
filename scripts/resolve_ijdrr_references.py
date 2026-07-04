"""Resolve IJDRR manuscript citation placeholders into numbered references.

The script applies a controlled reference map to the assembled Markdown files.
It preserves the original v2 files and writes *_refs_resolved.md outputs.
"""

from __future__ import annotations

from pathlib import Path


BASE = Path("F:/IJDRR write") / "\u8bba\u6587\u521d\u7a3f\u6a21\u5757"
EN_DASH = "\u2013"


REFERENCES = [
    "G.J. Rubin, M.B. Rogers, Behavioural and psychological responses of the public during a major power outage: A literature review, International Journal of Disaster Risk Reduction 38 (2019) 101226. https://doi.org/10.1016/j.ijdrr.2019.101226.",
    "J.J. Magoua, N. Li, The human factor in the disaster resilience modeling of critical infrastructure systems, Reliability Engineering & System Safety 232 (2023) 109073. https://doi.org/10.1016/j.ress.2022.109073.",
    "D. Helbing, P. Molnar, Social force model for pedestrian dynamics, Physical Review E 51 (1995) 4282-4286. https://doi.org/10.1103/PhysRevE.51.4282.",
    "D. Helbing, I. Farkas, T. Vicsek, Simulating dynamical features of escape panic, Nature 407 (2000) 487-490. https://doi.org/10.1038/35035023.",
    "J. Ren, Z. Mao, M. Gong, S. Zuo, Modified social force model considering emotional contagion for crowd evacuation simulation, International Journal of Disaster Risk Reduction 96 (2023) 103902. https://doi.org/10.1016/j.ijdrr.2023.103902.",
    "D. McFadden, Conditional logit analysis of qualitative choice behavior, in: P. Zarembka (Ed.), Frontiers in Econometrics, Academic Press, New York, 1974, pp. 105-142.",
    "R. Lovreglio, A discrete choice model based on random utilities for exit choice in emergency evacuations, Safety Science 82 (2016) 421-431.",
    "M. Haghani, M. Sarvi, Pedestrian crowd tactical-level decision making during emergency evacuations, Journal of Advanced Transportation 50 (2016) 1870-1895.",
    "R. Lovreglio, A. Fonzone, L. dell'Olio, A mixed logit model for predicting exit choice during building evacuations, Transportation Research Part A: Policy and Practice 92 (2016) 59-75. https://doi.org/10.1016/j.tra.2016.06.018.",
    "M. Moussaid, D. Helbing, G. Theraulaz, How simple rules determine pedestrian behavior and crowd disasters, Proceedings of the National Academy of Sciences 108 (2011) 6884-6888. https://doi.org/10.1073/pnas.1016507108.",
    "F. Durupinar, J. Allbeck, N. Pelechano, U. Gudukbay, N. Badler, How the OCEAN personality model affects the perception of crowds, IEEE Computer Graphics and Applications 31 (2011) 22-31.",
    "Y. Mao, S. Yang, Z. Li, Y. Li, Personality trait and group emotion contagion based crowd simulation for emergency evacuation, Multimedia Tools and Applications 79 (2020) 3077-3104. https://doi.org/10.1007/s11042-018-6069-3.",
    "M. Cao, G. Zhang, M. Wang, D. Lu, H. Liu, A method of emotion contagion for crowd evacuation, Physica A: Statistical Mechanics and its Applications 483 (2017) 250-258. https://doi.org/10.1016/j.physa.2017.04.137.",
    "G.-N. Wang, T. Chen, J.-W. Chen, K. Deng, R.-D. Wang, Simulation of crowd dynamics in pedestrian evacuation concerning panic contagion: A cellular automaton approach, Chinese Physics B 31 (2022) 060402. https://doi.org/10.1088/1674-1056/ac4a66.",
    "K.F. Yuen, X. Wang, F. Ma, K.X. Li, The psychological causes of panic buying following a health crisis, International Journal of Environmental Research and Public Health 17 (2020) 3513. https://doi.org/10.3390/ijerph17103513.",
    "S. Billore, T. Anisimova, Panic buying research: A systematic literature review and future research agenda, International Journal of Consumer Studies 45 (2021) 777-804.",
    "S. Nakano, M. Kondo, T. Kato, Consumer panic buying: Realizing its consequences and repercussions on the supply chain, International Journal of Management and Distribution 5 (2021) 17-35.",
    "L. Li, Q. Ma, M. Cao, Leveraging social media data to study community resilience to the 2019 Manhattan power outage, International Journal of Disaster Risk Reduction 51 (2020) 101776.",
    "A. Esmalian, W. Wang, A. Mostafavi, Multi-agent modeling of hazard-household-infrastructure nexus for equitable resilience assessment, Computer-Aided Civil and Infrastructure Engineering 37 (2022) 1491-1520. https://doi.org/10.1111/mice.12818.",
    "N. Carrington, I. Dobson, Z. Wang, Extracting resilience metrics from distribution utility data using outage and restore process statistics, IEEE Transactions on Power Systems 36 (2021) 5814-5823. https://doi.org/10.1109/TPWRS.2021.3074898.",
    "L.C. Freeman, A set of measures of centrality based on betweenness, Sociometry 40 (1977) 35-41.",
    "P. Crucitti, V. Latora, M. Marchiori, A. Rapisarda, Error and attack tolerance of complex networks, Physica A: Statistical Mechanics and its Applications 340 (2004) 388-394.",
    "E. Jenelius, T. Petersen, L.-G. Mattsson, Importance and exposure in road network vulnerability analysis, Transportation Research Part A: Policy and Practice 40 (2006) 537-560.",
    "R.S. Lazarus, S. Folkman, Stress, Appraisal, and Coping, Springer, New York, 1984.",
    "B.D. Greenshields, J.R. Bibbins, W.S. Channing, H.H. Miller, A study of traffic capacity, Proceedings of the Highway Research Board 14 (1935) 448-477.",
    "L. Qi, X. Cao, X. Xiong, C. Yang, X. Liao, Study on evacuation speed based on psychological panic in railway tunnel, E3S Web of Conferences 189 (2020) 03029. https://doi.org/10.1051/e3sconf/202018903029.",
    "G. Boeing, OSMnx: New methods for acquiring, constructing, analyzing, and visualizing complex street networks, Computers, Environment and Urban Systems 65 (2017) 126-139. https://doi.org/10.1016/j.compenvurbsys.2017.05.004.",
    "M.K. Lindell, R.W. Perry, The protective action decision model: Theoretical modifications and additional evidence, Risk Analysis 32 (2012) 616-632. https://doi.org/10.1111/j.1539-6924.2011.01647.x.",
    "T.J. Cova, J.P. Johnson, Microsimulation of neighborhood evacuations in the urban-wildland interface, Environment and Planning A 34 (2002) 2211-2229.",
]


SPECIFIC_REPLACEMENTS = {
    "[REF: Helbing & Moln\u00e1r, 1995; Helbing et al., 2000]": "@@CIT_3_4@@",
    "[REF: Helbing & Moln\u00e1r, 1995]": "@@CIT_3@@",
    "[REF: Moussa\u00efd et al., 2009]": "@@CIT_10@@",
    "[REF: Durupinar et al.; Zhou et al.]": "@@CIT_11_12@@",
    "[REF: Durupinar/ASCRIBE]": "@@CIT_11@@",
    "[REF: Wang et al.; Helbing]": "@@CIT_4_14@@",
    "[REF: Yuen et al., 2020; Billore & Anisimova, 2021]": "@@CIT_15_16@@",
    "[REF: Yuen et al., 2020]": "@@CIT_15@@",
    "[REF: Billore & Anisimova, 2021]": "@@CIT_16@@",
    "[REF: panic-buying review]": "@@CIT_16@@",
    "[REF: panic-buying segmentation study]": "@@CIT_17@@",
    "[REF: Rubin & Rogers, 2019, IJDRR 38:101226]": "@@CIT_1@@",
    "[REF: Rubin & Rogers, 2019]": "@@CIT_1@@",
    "[REF: Manhattan-2019 resilience study, IJDRR]": "@@CIT_18@@",
    "[REF: Freeman, 1977]": "@@CIT_21@@",
    "[REF: Crucitti et al., 2006; Jenelius et al., 2006; disaster-network-centrality refs]": "@@CIT_22_23@@",
    "[REF: Lazarus & Folkman, 1984]": "@@CIT_24@@",
    "[REF: Greenshields, 1934]": "@@CIT_25@@",
    "[REF: panic-speed-factor study]": "@@CIT_26@@",
    "[REF: Boeing, 2017]": "@@CIT_27@@",
    "[REF: Lindell & Perry, 2012 *Protective Action Decision Model*]": "@@CIT_28@@",
    "[REF: Cova & Johnson, 2008 *traffic-shed evacuation*]": "@@CIT_29@@",
    "[REF: provincial DRM bureaus]": "",
}


NUMERIC_REPLACEMENTS = {
    f"[26{EN_DASH}29]": "@@CIT_6_9@@",
    "[26-29]": "@@CIT_6_9@@",
    f"[27{EN_DASH}29]": "@@CIT_7_9@@",
    "[27-29]": "@@CIT_7_9@@",
    f"[33{EN_DASH}35]": "@@CIT_2_19_20@@",
    "[33-35]": "@@CIT_2_19_20@@",
    "[26]": "@@CIT_6@@",
    "[27]": "@@CIT_7@@",
    "[28]": "@@CIT_8@@",
    "[29]": "@@CIT_9@@",
    "[30]": "@@CIT_4@@",
    "[31]": "@@CIT_5@@",
    "[32]": "@@CIT_13@@",
}


CITATIONS = {
    "@@CIT_1@@": "[1]",
    "@@CIT_1_2@@": "[1,2]",
    "@@CIT_2_19_20@@": "[2,19,20]",
    "@@CIT_3@@": "[3]",
    "@@CIT_3_4@@": "[3,4]",
    "@@CIT_3_5@@": "[3-5]",
    "@@CIT_4@@": "[4]",
    "@@CIT_4_14@@": "[4,14]",
    "@@CIT_5@@": "[5]",
    "@@CIT_6@@": "[6]",
    "@@CIT_6_9@@": "[6-9]",
    "@@CIT_7@@": "[7]",
    "@@CIT_7_9@@": "[7-9]",
    "@@CIT_8@@": "[8]",
    "@@CIT_9@@": "[9]",
    "@@CIT_10@@": "[10]",
    "@@CIT_11@@": "[11]",
    "@@CIT_11_12@@": "[11,12]",
    "@@CIT_13@@": "[13]",
    "@@CIT_14@@": "[14]",
    "@@CIT_15@@": "[15]",
    "@@CIT_15_16@@": "[15,16]",
    "@@CIT_16@@": "[16]",
    "@@CIT_17@@": "[17]",
    "@@CIT_18@@": "[18]",
    "@@CIT_21@@": "[21]",
    "@@CIT_22_23@@": "[22,23]",
    "@@CIT_24@@": "[24]",
    "@@CIT_25@@": "[25]",
    "@@CIT_26@@": "[26]",
    "@@CIT_27@@": "[27]",
    "@@CIT_28@@": "[28]",
    "@@CIT_29@@": "[29]",
}


INTRO_REPLACEMENTS = {
    "Disaster-risk-reduction (DRR) planning needs models that can represent this behavioural layer at the same spatial resolution as the road and shelter network on which emergency movement actually occurs [REF].": "Disaster-risk-reduction (DRR) planning needs models that can represent this behavioural layer at the same spatial resolution as the road and shelter network on which emergency movement actually occurs @@CIT_1_2@@.",
    "Social-force models and their psychological extensions have made substantial progress in representing acceleration, interpersonal forces, density effects, emotional contagion and heterogeneous stress responses [REF].": "Social-force models and their psychological extensions have made substantial progress in representing acceleration, interpersonal forces, density effects, emotional contagion and heterogeneous stress responses @@CIT_3_5@@.",
}


def reference_section() -> str:
    lines = ["# References", ""]
    for idx, entry in enumerate(REFERENCES, 1):
        lines.append(f"[{idx}] {entry}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def replace_reference_section(text: str) -> str:
    marker = "# References"
    idx = text.find(marker)
    if idx == -1:
        return text.rstrip() + "\n\n" + reference_section()
    supplement_idx = text.find("# Supplementary Material", idx)
    if supplement_idx == -1:
        return text[:idx].rstrip() + "\n\n" + reference_section()
    return text[:idx].rstrip() + "\n\n" + reference_section().rstrip() + "\n\n" + text[supplement_idx:].lstrip()


def resolve_text(text: str, include_reference_section: bool) -> str:
    for old, new in INTRO_REPLACEMENTS.items():
        text = text.replace(old, new)
    for old, new in SPECIFIC_REPLACEMENTS.items():
        text = text.replace(old, new)
    for old, new in NUMERIC_REPLACEMENTS.items():
        text = text.replace(old, new)
    for token, citation in CITATIONS.items():
        text = text.replace(token, citation)

    text = text.replace(
        "Estimate the MNL coefficients of Table 2 from existing stated-preference surveys conducted around the 2008 Wenchuan earthquake and the 2021 Henan floods .",
        "Estimate the MNL coefficients of Table 2 from stated-preference surveys or post-event behavioural datasets for Chinese evacuation contexts, including earthquake and flood cases where suitable records are available.",
    )
    text = text.replace(
        "Estimate the MNL coefficients of Table 2 from existing stated-preference surveys conducted around the 2008 Wenchuan earthquake and the 2021 Henan floods . Predict:",
        "Estimate the MNL coefficients of Table 2 from stated-preference surveys or post-event behavioural datasets for Chinese evacuation contexts, including earthquake and flood cases where suitable records are available. Predict:",
    )

    if include_reference_section:
        text = replace_reference_section(text)
    return text


def main() -> None:
    jobs = [
        ("IJDRR_main_manuscript_v2.md", "IJDRR_main_manuscript_v2_refs_resolved.md", True),
        ("IJDRR_full_paper_v2.md", "IJDRR_full_paper_v2_refs_resolved.md", True),
        ("IJDRR_supplementary_material_v2.md", "IJDRR_supplementary_material_v2_refs_resolved.md", False),
    ]
    for src, dst, include_refs in jobs:
        text = (BASE / src).read_text(encoding="utf-8")
        resolved = resolve_text(text, include_refs)
        if not include_refs:
            resolved = resolved.rstrip() + "\n\n*Reference numbering follows the main manuscript reference list.*\n"
        (BASE / dst).write_text(resolved, encoding="utf-8")
        print(f"wrote {BASE / dst}")


if __name__ == "__main__":
    main()
