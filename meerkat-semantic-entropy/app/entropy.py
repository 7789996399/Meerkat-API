import math

from .models import ClusterInfo


def compute_semantic_entropy(
    cluster_groups: dict[int, list[int]],
    completions: list[str],
    total_n: int,
) -> tuple[float, float, list[ClusterInfo]]:
    """
    Compute semantic entropy from cluster groups.

    Returns (raw_entropy, normalized_entropy, cluster_info_list).
    """
    cluster_infos: list[ClusterInfo] = []
    probabilities: list[float] = []

    for cid, (root, members) in enumerate(sorted(cluster_groups.items())):
        p = len(members) / total_n
        probabilities.append(p)

        # Representative = shortest completion in the cluster
        representative = min((completions[i] for i in members), key=len)

        cluster_infos.append(ClusterInfo(
            cluster_id=cid,
            size=len(members),
            representative=representative,
            members=sorted(members),
        ))

    # Shannon entropy: H = -sum(p * log(p))
    raw_entropy = -sum(p * math.log(p) for p in probabilities if p > 0)

    # Normalize by log(N) so result is in [0, 1]
    max_entropy = math.log(total_n) if total_n > 1 else 1.0
    normalized = raw_entropy / max_entropy if max_entropy > 0 else 0.0
    normalized = min(1.0, max(0.0, normalized))

    return raw_entropy, normalized, cluster_infos


def interpret_entropy(normalized: float) -> str:
    if normalized < 0.1:
        return "certain"
    if normalized < 0.3:
        return "low_uncertainty"
    if normalized < 0.5:
        return "moderate_uncertainty"
    if normalized < 0.7:
        return "high_uncertainty"
    return "confabulation_likely"
