from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from outlierlab.core.detectors.base import DetectorFamily, DetectorSpec

ParamKind = Literal["choice", "int", "float"]


@dataclass(frozen=True)
class ParamSpec:
    """Metadata describing a tunable detector parameter."""

    key: str
    label: str
    kind: ParamKind
    default: Any
    hint: str = ""
    min_val: float | None = None
    max_val: float | None = None
    step: float | None = None
    choices: tuple[str, ...] = ()
    is_percent: bool = False


@dataclass(frozen=True)
class DetectorMeta:
    """Catalogue entry for a supported detector."""

    key: str
    name: str
    short_name: str
    library: Literal["ruptures", "PyOD"]
    class_path: str
    family: DetectorFamily
    uses_seed: bool
    description: str
    params: tuple[ParamSpec, ...]


DETECTOR_REGISTRY: dict[str, DetectorMeta] = {
    "pelt": DetectorMeta(
        key="pelt",
        name="PELT",
        short_name="PELT",
        library="ruptures",
        class_path="ruptures.Pelt",
        family="changepoint",
        uses_seed=False,
        description="Finds the best set of change points for a given penalty. Exact and fast.",
        params=(
            ParamSpec("model", "Cost model", "choice", "rbf", "l2: mean shifts; rbf: mean or spread shifts.", choices=("l2", "l1", "rbf")),
            ParamSpec("pen", "Penalty", "int", 10, "Higher penalty produces fewer change points.", min_val=1, max_val=60, step=1),
            ParamSpec("min_size", "Min segment length", "int", 2, "Shortest stretch between two changes, in samples.", min_val=1, max_val=50, step=1),
            ParamSpec("jump", "Jump", "int", 5, "Only every n-th sample can be a change point.", min_val=1, max_val=20, step=1),
        ),
    ),
    "binseg": DetectorMeta(
        key="binseg",
        name="Binary segmentation",
        short_name="Binseg",
        library="ruptures",
        class_path="ruptures.Binseg",
        family="changepoint",
        uses_seed=False,
        description="Splits the series at the strongest change, then repeats inside each half.",
        params=(
            ParamSpec("model", "Cost model", "choice", "l2", "What counts as a change.", choices=("l2", "l1", "rbf")),
            ParamSpec("n_bkps", "Number of changes", "int", 4, "Stop after this many change points.", min_val=1, max_val=10, step=1),
            ParamSpec("min_size", "Min segment length", "int", 2, "In samples.", min_val=1, max_val=50, step=1),
            ParamSpec("jump", "Jump", "int", 5, "Only every n-th sample can be a change point.", min_val=1, max_val=20, step=1),
        ),
    ),
    "bottomup": DetectorMeta(
        key="bottomup",
        name="Bottom-up",
        short_name="Bottom-up",
        library="ruptures",
        class_path="ruptures.BottomUp",
        family="changepoint",
        uses_seed=False,
        description="Starts with many small segments and merges the most similar neighbours.",
        params=(
            ParamSpec("model", "Cost model", "choice", "l2", "What counts as a change.", choices=("l2", "l1", "rbf")),
            ParamSpec("n_bkps", "Number of changes", "int", 4, "Stop when this many remain.", min_val=1, max_val=10, step=1),
            ParamSpec("min_size", "Min segment length", "int", 2, "In samples.", min_val=1, max_val=50, step=1),
            ParamSpec("jump", "Jump", "int", 5, "Only every n-th sample can be a change point.", min_val=1, max_val=20, step=1),
        ),
    ),
    "window": DetectorMeta(
        key="window",
        name="Sliding window",
        short_name="Window",
        library="ruptures",
        class_path="ruptures.Window",
        family="changepoint",
        uses_seed=False,
        description="Compares the window before each point with the window after it.",
        params=(
            ParamSpec("width", "Window width", "int", 40, "Samples on each side. Wide windows ignore short spikes.", min_val=10, max_val=200, step=2),
            ParamSpec("model", "Cost model", "choice", "l2", "What counts as a change.", choices=("l2", "l1", "rbf")),
            ParamSpec("n_bkps", "Number of changes", "int", 4, "Keep the strongest n.", min_val=1, max_val=10, step=1),
            ParamSpec("jump", "Jump", "int", 5, "Only every n-th sample can be a change point.", min_val=1, max_val=20, step=1),
        ),
    ),
    "kernel": DetectorMeta(
        key="kernel",
        name="Kernel change detection",
        short_name="KernelCPD",
        library="ruptures",
        class_path="ruptures.KernelCPD",
        family="changepoint",
        uses_seed=False,
        description="Like PELT, with a kernel that can detect changes in distribution shape.",
        params=(
            ParamSpec("kernel", "Kernel", "choice", "rbf", "rbf is a safe default.", choices=("linear", "rbf", "cosine")),
            ParamSpec("pen", "Penalty", "int", 12, "Higher penalty produces fewer change points.", min_val=1, max_val=60, step=1),
            ParamSpec("min_size", "Min segment length", "int", 2, "In samples.", min_val=1, max_val=50, step=1),
        ),
    ),
    "iforest": DetectorMeta(
        key="iforest",
        name="Isolation Forest",
        short_name="IForest",
        library="PyOD",
        class_path="pyod.models.iforest.IForest",
        family="anomaly",
        uses_seed=True,
        description="Random trees isolate unusual windows quickly. Uses the global seed.",
        params=(
            ParamSpec("n_estimators", "Number of trees", "int", 100, "More trees give steadier scores, slower.", min_val=10, max_val=500, step=10),
            ParamSpec("contamination", "Expected anomalies", "float", 0.02, "Share of points flagged.", min_val=0.005, max_val=0.1, step=0.005, is_percent=True),
            ParamSpec("window", "Window size", "int", 25, "Each point is judged with this many neighbours.", min_val=5, max_val=100, step=1),
        ),
    ),
    "lof": DetectorMeta(
        key="lof",
        name="Local Outlier Factor",
        short_name="LOF",
        library="PyOD",
        class_path="pyod.models.lof.LOF",
        family="anomaly",
        uses_seed=False,
        description="Flags points much less dense than their neighbours.",
        params=(
            ParamSpec("n_neighbors", "Neighbours", "int", 20, "Small catches local spikes; large catches big outliers.", min_val=5, max_val=100, step=1),
            ParamSpec("contamination", "Expected anomalies", "float", 0.02, "Share of points flagged.", min_val=0.005, max_val=0.1, step=0.005, is_percent=True),
            ParamSpec("window", "Window size", "int", 25, "Each point is judged with this many neighbours.", min_val=5, max_val=100, step=1),
        ),
    ),
    "knn": DetectorMeta(
        key="knn",
        name="k-Nearest Neighbours",
        short_name="KNN",
        library="PyOD",
        class_path="pyod.models.knn.KNN",
        family="anomaly",
        uses_seed=False,
        description="Distance to the k-th nearest neighbour is the anomaly score.",
        params=(
            ParamSpec("n_neighbors", "Neighbours (k)", "int", 5, "PyOD default is 5.", min_val=1, max_val=50, step=1),
            ParamSpec("method", "Distance", "choice", "largest", "Which neighbour distance to use.", choices=("largest", "mean", "median")),
            ParamSpec("contamination", "Expected anomalies", "float", 0.02, "Share of points flagged.", min_val=0.005, max_val=0.1, step=0.005, is_percent=True),
            ParamSpec("window", "Window size", "int", 25, "Each point is judged with this many neighbours.", min_val=5, max_val=100, step=1),
        ),
    ),
    "ecod": DetectorMeta(
        key="ecod",
        name="ECOD",
        short_name="ECOD",
        library="PyOD",
        class_path="pyod.models.ecod.ECOD",
        family="anomaly",
        uses_seed=False,
        description="Scores how far each point sits in the tails of the data.",
        params=(
            ParamSpec("contamination", "Expected anomalies", "float", 0.02, "Share of points flagged.", min_val=0.005, max_val=0.1, step=0.005, is_percent=True),
            ParamSpec("window", "Window size", "int", 25, "Each point is judged with this many neighbours.", min_val=5, max_val=100, step=1),
        ),
    ),
    "ocsvm": DetectorMeta(
        key="ocsvm",
        name="One-class SVM",
        short_name="OCSVM",
        library="PyOD",
        class_path="pyod.models.ocsvm.OCSVM",
        family="anomaly",
        uses_seed=False,
        description="Learns a boundary around normal windows.",
        params=(
            ParamSpec("kernel", "Kernel", "choice", "rbf", "rbf suits most sensor data.", choices=("rbf", "linear", "poly", "sigmoid")),
            ParamSpec("nu", "nu", "float", 0.5, "Upper bound on training errors.", min_val=0.01, max_val=0.5, step=0.01),
            ParamSpec("contamination", "Expected anomalies", "float", 0.02, "Share of points flagged.", min_val=0.005, max_val=0.1, step=0.005, is_percent=True),
            ParamSpec("window", "Window size", "int", 25, "Each point is judged with this many neighbours.", min_val=5, max_val=100, step=1),
        ),
    ),
}


def get_detector_meta(key: str) -> DetectorMeta:
    """Return metadata for a registered detector key."""
    if key not in DETECTOR_REGISTRY:
        raise KeyError(f"Unknown detector key: {key!r}")
    return DETECTOR_REGISTRY[key]


def list_detectors(family: DetectorFamily | None = None) -> list[DetectorMeta]:
    """Return all registered detectors, optionally filtered by family."""
    items = list(DETECTOR_REGISTRY.values())
    if family is not None:
        items = [m for m in items if m.family == family]
    return items


def default_params(key: str) -> dict[str, Any]:
    """Return a fresh dict of default parameter values for a detector."""
    meta = get_detector_meta(key)
    return {p.key: p.default for p in meta.params}


def make_default_spec(key: str, enabled: bool = True) -> DetectorSpec:
    """Create a DetectorSpec populated with registry defaults."""
    meta = get_detector_meta(key)
    return DetectorSpec(
        key=meta.key,
        name=meta.short_name,
        params=default_params(key),
        enabled=enabled,
    )