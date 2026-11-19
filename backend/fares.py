# Demo route: Stage A → Stage B → Stage C.
# Each fare is a sample amount in whole Kenya shillings.
SAMPLE_FARES_KES = {
    ("stage-a", "stage-b"): 30,
    ("stage-a", "stage-c"): 50,
    ("stage-b", "stage-c"): 30,
}


def calculate_fare(boarding_stage: str, alighting_stage: str) -> int:
    fare = SAMPLE_FARES_KES.get((boarding_stage, alighting_stage))
    if fare is None:
        raise ValueError(
            f"No fare configured from {boarding_stage} to {alighting_stage}."
        )
    return fare
