"""Random draw of the starting grids (pure logic, no database)."""
from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Entrant:
    bike_id: int
    rider_id: int


class DrawError(Exception):
    pass


def turn_count(entrants: list[Entrant], max_per_grid: int = 8) -> int:
    """Turns needed: enough for the size limit, and one per bike of the busiest rider."""
    if not entrants:
        return 0
    most_bikes = max(Counter(e.rider_id for e in entrants).values())
    return max(math.ceil(len(entrants) / max_per_grid), most_bikes)


def turn_sizes(n: int, turns: int) -> list[int]:
    """Split n bikes into `turns` grids whose sizes differ by at most one (9, 2 -> [5, 4])."""
    return [n // turns + (1 if i < n % turns else 0) for i in range(turns)]


def draw_class(
    entrants: list[Entrant],
    max_per_grid: int = 8,
    rng: random.Random | None = None,
    attempts: int = 200,
) -> list[list[int]]:
    """Randomly split one class into turns.

    Returns a list of turns, each a list of bike ids in starting order (position 1 first).
    A rider never has two bikes in the same turn.
    """
    rng = rng or random.Random()
    turns = turn_count(entrants, max_per_grid)
    if turns == 0:
        return []
    sizes = turn_sizes(len(entrants), turns)
    bikes_per_rider = Counter(e.rider_id for e in entrants)

    for _ in range(attempts):
        order = list(entrants)
        rng.shuffle(order)
        # Riders with more bikes go first, so they can always be spread across turns.
        order.sort(key=lambda e: -bikes_per_rider[e.rider_id])
        result: list[list[Entrant]] = [[] for _ in range(turns)]
        for entrant in order:
            options = [
                i for i in range(turns)
                if len(result[i]) < sizes[i]
                and all(o.rider_id != entrant.rider_id for o in result[i])
            ]
            if not options:
                break
            room = max(sizes[i] - len(result[i]) for i in options)
            result[rng.choice([i for i in options if sizes[i] - len(result[i]) == room])].append(entrant)
        else:
            for turn in result:
                rng.shuffle(turn)
            return [[e.bike_id for e in turn] for turn in result]
    raise DrawError("Impossibile comporre le batterie rispettando i vincoli")
