from typing import Any, List, OrderedDict

from scalene.scalene_statistics import Filename, LineNumber, ScaleneStatistics


class ScaleneLeakAnalysis:

    # Only report potential leaks if the allocation velocity is above this threshold
    growth_rate_threshold = 0.01

    # Only report leaks whose likelihood is 1 minus this threshold
    leak_reporting_threshold = 0.05

    @staticmethod
    def compute_leaks(
        growth_rate: float,
        stats: ScaleneStatistics,
        avg_mallocs: OrderedDict[LineNumber, float],
        fname: Filename,
    ) -> List[Any]:
        if growth_rate / 100 < ScaleneLeakAnalysis.growth_rate_threshold:
            return []
        leaks = []
        keys = list(stats.leak_score[fname].keys())
        for index, item in enumerate(stats.leak_score[fname].values()):
            # See https://en.wikipedia.org/wiki/Rule_of_succession
            allocs = item[0]
            frees = item[1]
            # Successful reclamations are given by the number of frees.
            # Failures - no reclamations seen - are given by the number of allocs with no matching frees (allocs - frees).
            expected_leak = 1.0 - (frees + 1) / (allocs - frees + 2)

            if (
                expected_leak
                >= 1.0 - ScaleneLeakAnalysis.leak_reporting_threshold
            ):
                if keys[index] in avg_mallocs:
                    leaks.append(
                        (
                            keys[index],
                            expected_leak,
                            avg_mallocs[keys[index]],
                        )
                    )
        return leaks
